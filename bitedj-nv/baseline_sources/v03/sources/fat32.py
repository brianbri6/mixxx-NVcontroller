"""Small FAT32 reader for the project's boot partition inspection."""
from pathlib import Path
import struct


class Fat32:
    def __init__(self,path):
        self.data=bytearray(Path(path).read_bytes())
        self.sector=struct.unpack_from('<H',self.data,11)[0]
        self.cluster_size=self.data[13]*self.sector
        reserved=struct.unpack_from('<H',self.data,14)[0]
        fats=self.data[16]; fat_sectors=struct.unpack_from('<I',self.data,36)[0]
        self.fats=fats; self.fat_bytes=fat_sectors*self.sector
        self.fat_at=reserved*self.sector
        self.data_at=(reserved+fats*fat_sectors)*self.sector
        self.root=struct.unpack_from('<I',self.data,44)[0]
        if self.data[510:512]!=b'\x55\xaa':raise ValueError('Invalid boot partition')

    def clusters(self,cluster):
        result=[]; seen=set()
        while 2<=cluster<0x0ffffff8:
            if cluster in seen:raise ValueError('FAT loop')
            seen.add(cluster);result.append(cluster)
            cluster=struct.unpack_from('<I',self.data,self.fat_at+cluster*4)[0]&0x0fffffff
        return result

    def chain(self,cluster):
        return b''.join(self.data[self.data_at+(n-2)*self.cluster_size:self.data_at+(n-1)*self.cluster_size]
                        for n in self.clusters(cluster))

    def entries(self,cluster=None):
        dir_clusters=self.clusters(self.root if cluster is None else cluster)
        directory=self.chain(self.root if cluster is None else cluster); long_parts={}; result=[]
        for at in range(0,len(directory),32):
            entry=directory[at:at+32]
            if entry[0]==0:break
            if entry[0]==0xe5:long_parts.clear();continue
            if entry[11]==0x0f:
                units=entry[1:11]+entry[14:26]+entry[28:32]
                long_parts[entry[0]&0x1f]=units.decode('utf-16-le').split('\x00',1)[0].rstrip('\uffff')
                continue
            short=entry[:8].decode('ascii').rstrip();ext=entry[8:11].decode('ascii').rstrip()
            if entry[12]&8:short=short.lower()
            if entry[12]&16:ext=ext.lower()
            short+='.'+ext if ext else ''
            name=''.join(long_parts[n] for n in sorted(long_parts)) if long_parts else short
            long_parts.clear()
            if entry[11]&8 or name in ['.','..']:continue
            cluster=(struct.unpack_from('<H',entry,20)[0]<<16)|struct.unpack_from('<H',entry,26)[0]
            entry_offset=self.data_at+(dir_clusters[at//self.cluster_size]-2)*self.cluster_size+at%self.cluster_size
            result.append({'name':name,'cluster':cluster,'size':struct.unpack_from('<I',entry,28)[0], 'offset':entry_offset,
                           'directory':bool(entry[11]&16)})
        return result

    def extract(self,destination,cluster=None):
        dest=Path(destination);dest.mkdir(parents=True,exist_ok=True)
        for item in self.entries(cluster):
            path=dest/item['name']
            if '/' in item['name'] or '\\' in item['name']:raise ValueError('Unsafe FAT name')
            if item['directory']:self.extract(path,item['cluster'])
            else:
                data=self.chain(item['cluster'])[:item['size']]
                if len(data)!=item['size']:raise ValueError('Truncated FAT file')
                path.write_bytes(data)

    def set_fat(self,cluster,value):
        for copy in range(self.fats):
            struct.pack_into('<I',self.data,self.fat_at+copy*self.fat_bytes+cluster*4,value)

    def replace(self,name,payload):
        entry=next(x for x in self.entries() if x['name'].casefold()==name.casefold())
        if entry['directory']:raise ValueError('Cannot replace a directory')
        for n in self.clusters(entry['cluster']):
            self.set_fat(n,0)
            at=self.data_at+(n-2)*self.cluster_size
            self.data[at:at+self.cluster_size]=b'\0'*self.cluster_size
        needed=(len(payload)+self.cluster_size-1)//self.cluster_size
        capacity=(len(self.data)-self.data_at)//self.cluster_size
        free=[n for n in range(2,capacity+2) if struct.unpack_from('<I',self.data,self.fat_at+n*4)[0]&0x0fffffff==0]
        if len(free)<needed:raise ValueError('Boot partition is full')
        chain=free[:needed]
        for i,n in enumerate(chain):
            self.set_fat(n,chain[i+1] if i+1<len(chain) else 0x0fffffff)
            at=self.data_at+(n-2)*self.cluster_size
            self.data[at:at+self.cluster_size]=payload[i*self.cluster_size:(i+1)*self.cluster_size].ljust(self.cluster_size,b'\0')
        first=chain[0] if chain else 0;at=entry['offset']
        struct.pack_into('<H',self.data,at+20,first>>16)
        struct.pack_into('<H',self.data,at+26,first&0xffff)
        struct.pack_into('<I',self.data,at+28,len(payload))

    def validate(self):
        expected=self.data[self.fat_at:self.fat_at+self.fat_bytes]
        for copy in range(1,self.fats):
            assert expected==self.data[self.fat_at+copy*self.fat_bytes:self.fat_at+(copy+1)*self.fat_bytes]
        used=set()
        def walk(cluster):
            chain=self.clusters(cluster)
            assert not used.intersection(chain),'Cross-linked directory'
            used.update(chain)
            for entry in self.entries(cluster):
                if entry['directory']:walk(entry['cluster'])
                else:
                    chain=self.clusters(entry['cluster'])
                    assert len(chain)*self.cluster_size>=entry['size'],'Truncated file'
                    assert not used.intersection(chain),'Cross-linked file'
                    used.update(chain)
        walk(self.root)
        capacity=(len(self.data)-self.data_at)//self.cluster_size
        allocated={n for n in range(2,capacity+2) if struct.unpack_from('<I',self.data,self.fat_at+n*4)[0]&0x0fffffff}
        assert used==allocated,('Unreferenced allocated clusters',len(allocated-used))
        return {'fat_copies_match':True,'crosslinks':0,'allocated_clusters':len(allocated),'free_clusters':capacity-len(allocated)}

    def save(self,path):
        stats=self.validate()
        fsinfo=struct.unpack_from('<H',self.data,48)[0]
        backup=struct.unpack_from('<H',self.data,50)[0]
        for sector in [fsinfo,backup+fsinfo]:
            at=sector*self.sector
            if self.data[at:at+4]==b'RRaA' and self.data[at+484:at+488]==b'rrAa':
                struct.pack_into('<II',self.data,at+488,stats['free_clusters'],0xffffffff)
        Path(path).write_bytes(self.data)
        return stats


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('partition');parser.add_argument('destination')
    args=parser.parse_args(); reader=Fat32(args.partition)
    print(reader.entries());reader.extract(args.destination)
