// SPDX-License-Identifier: GPL-2.0-or-later
#include "controllers/numarknvexporter.h"

#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocale>
#include <QPointer>
#include <QTimer>
#include <QUuid>
#include <QtDebug>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "control/controlproxy.h"
#include "effects/effectsmanager.h"
#include "effects/effectchain.h"
#include "effects/effectslot.h"
#include "library/library.h"
#include "library/trackmodel.h"
#include "mixer/basetrackplayer.h"
#include "mixer/playermanager.h"
#include "track/track.h"
#include "waveform/waveform.h"
#include "widget/wlibrary.h"
#include "widget/wlibrarysidebar.h"
#include "widget/wtracktableview.h"

namespace {
constexpr int kDecks = 4;
constexpr int kOverviewColumns = 240;
constexpr int kDetailColumns = 480;
constexpr int kColumnsPerSecond = 240;
constexpr std::array<const char*, 8> kControls{
        "playposition", "bpm", "rate", "rateRange", "rate_dir",
        "play_indicator", "beat_distance", "track_loaded"};

double finiteValue(double value, double fallback = 0.0) {
    return std::isfinite(value) ? value : fallback;
}

// Four bands per column, stereo channels combined by maximum. Read only
// samples published by the analyzer's acquire/release completion counter.
QByteArray peaks(const ConstWaveformPointer& waveform,
        int columns, double beginFrame, double framesPerColumn) {
    QByteArray result(columns * 4, '\0');
    if (!waveform || framesPerColumn <= 0.0 || !std::isfinite(framesPerColumn)) {
        return result;
    }
    const int frames = std::min(waveform->getCompletion(), waveform->getDataSize()) / 2;
    if (frames <= 0) {
        return result;
    }
    for (int x = 0; x < columns; ++x) {
        const double a = beginFrame + x * framesPerColumn;
        const double b = a + framesPerColumn;
        const int first = static_cast<int>(std::clamp(std::floor(a), 0.0, double(frames)));
        const int last = static_cast<int>(std::clamp(std::ceil(b), 0.0, double(frames)));
        unsigned char maximum[4]{};
        for (int frame = first; frame < last; ++frame) {
            for (int channel = 0; channel < 2; ++channel) {
                const auto& v = waveform->get(frame * 2 + channel).filtered;
                maximum[0] = std::max(maximum[0], v.low);
                maximum[1] = std::max(maximum[1], v.mid);
                maximum[2] = std::max(maximum[2], v.high);
                maximum[3] = std::max(maximum[3], v.all);
            }
        }
        for (int band = 0; band < 4; ++band) {
            result[x * 4 + band] = static_cast<char>(maximum[band]);
        }
    }
    return result;
}
} // namespace

struct NumarkNvExporter::Impl {
    struct Deck {
        TrackPointer track;
        int generation = 0;
        std::array<std::unique_ptr<ControlProxy>, kControls.size()> controls;
        QByteArray overview;
        qint64 lastOverview = -1000;
        const Waveform* overviewSource = nullptr;
        double value(size_t index) const {
            return controls[index] ? finiteValue(controls[index]->get()) : 0.0;
        }
    };
    PlayerManager* players;
    EffectsManager* effects; // Outlives PlayerManager / this exporter.
    QPointer<Library> library;
    QJsonArray effectState;
    QJsonObject browserState;
    QString heading;
    qint64 lastAuxiliary = -200;
    QTimer timer;
    QElapsedTimer clock;
    std::array<Deck, kDecks> decks;
    QString session = QUuid::createUuid().toString(QUuid::WithoutBraces);
    sockaddr_un address{};
    int fd = -1;
    bool detail = qgetenv("BITEDJ_NV_DETAIL") != "0";

    Impl(PlayerManager* manager, EffectsManager* effectManager, Library* libraryManager)
            : players(manager), effects(effectManager), library(libraryManager) {
        const QByteArray path = qgetenv("BITEDJ_NV_SOCKET");
        if (path.isEmpty()) {
            return;
        }
        if (path.size() >= static_cast<int>(sizeof(address.sun_path))) {
            qWarning() << "NV telemetry socket path too long; disabled";
            return;
        }
        address.sun_family = AF_UNIX;
        std::memcpy(address.sun_path, path.constData(), path.size());
        fd = ::socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
        if (fd < 0) {
            qWarning() << "NV telemetry socket creation failed; disabled";
            return;
        }
        clock.start();
        if (library) {
            QObject::connect(library, &Library::sidebarLeafItemActivated, &timer,
                    [this](const QString& title) { heading = title.left(128); });
        }
        QObject::connect(&timer, &QTimer::timeout, &timer, [this] { publish(); });
        timer.start(50);
        qInfo() << "NV telemetry enabled, 20 Hz, socket" << path;
    }

    ~Impl() {
        timer.stop();
        if (fd >= 0) {
            ::close(fd);
        }
    }

    void sampleAuxiliary() {
        effectState = QJsonArray();
        // The original NV has three text slots on each screen. Mirror the
        // corresponding standard units; do not create or change any effect.
        for (int unit = 0; unit < 2; ++unit) {
            QJsonArray labels;
            const auto chain = effects ? effects->getStandardEffectChain(unit) : EffectChainPointer();
            if (chain) {
                const auto& effectSlots = chain->getEffectSlots();
                for (int i = 0; i < std::min(3, int(effectSlots.size())); ++i) {
                    const auto& slot = effectSlots[i];
                    const auto manifest = slot ? slot->getManifest() : EffectManifestPointer();
                    labels.append(QJsonObject{
                            {"name", slot && slot->isLoaded() && manifest
                                            ? manifest->displayName().left(128) : QString()},
                            {"meta_percent", slot ? std::clamp(finiteValue(slot->getMetaParameter()), 0.0, 1.0) * 100.0 : 0.0}});
                }
            }
            effectState.append(QJsonObject{{"unit", unit + 1}, {"slots", labels}});
        }

        browserState = QJsonObject{{"available", false}, {"heading", QString()},
                {"folders", QJsonArray()}, {"selected_folder", -1},
                {"tracks", QJsonArray()}, {"selected_row", -1},
                {"first_row", 0}, {"total_rows", 0}};
        if (!library) {
            return;
        }
        auto* widget = library->nvLibraryWidget();
        // WLibrary's accessor dereferences currentWidget(); a skin being
        // constructed/reloaded can have no active page yet.
        auto* table = widget && widget->currentWidget() ? widget->getCurrentTrackTableView() : nullptr;
        auto* model = table ? table->model() : nullptr;
        auto* trackModel = dynamic_cast<TrackModel*>(model);
        auto* sidebar = library->nvSidebarWidget();
        browserState["heading"] = heading.isEmpty() && sidebar
                ? sidebar->currentIndex().data().toString().left(128) : heading;
        if (sidebar && sidebar->model()) {
            const QModelIndex selected = sidebar->currentIndex().siblingAtColumn(0);
            QModelIndex first = selected.isValid() ? selected : sidebar->model()->index(0, 0);
            for (int i = 0; i < 3; ++i) {
                const QModelIndex above = sidebar->indexAbove(first);
                if (!above.isValid()) break;
                first = above;
            }
            QJsonArray folders;
            for (auto index = first; index.isValid() && folders.size() < 8;
                    index = sidebar->indexBelow(index)) {
                if (index == selected) browserState["selected_folder"] = folders.size();
                folders.append(index.data().toString().left(128));
            }
            browserState["folders"] = folders;
        }
        if (!model || !trackModel) {
            return;
        }
        // Read the existing active table only. No getTrack(), file scan or
        // additional metadata loading on the GUI thread.
        const int total = model->rowCount();
        const auto current = table->currentIndex();
        const int selected = current.isValid() ? current.row() : -1;
        const int first = std::clamp(selected - 3, 0, std::max(0, total - 7));
        const auto column = [trackModel](TrackModel::SortColumnId id) {
            return trackModel->columnIndexFromSortColumnId(id);
        };
        const auto cell = [model](int row, int col, int role = Qt::DisplayRole) {
            return col >= 0 ? model->index(row, col).data(role) : QVariant();
        };
        const int titleCol = column(TrackModel::SortColumnId::Title);
        const int artistCol = column(TrackModel::SortColumnId::Artist);
        const int bpmCol = column(TrackModel::SortColumnId::Bpm);
        const int filenameCol = column(TrackModel::SortColumnId::Filename);
        QJsonArray tracks;
        for (int row = first; row < std::min(total, first + 7); ++row) {
            QString title = cell(row, titleCol).toString();
            if (title.isEmpty()) title = cell(row, filenameCol).toString();
            const auto bpmCell = cell(row, bpmCol, Qt::EditRole);
            bool ok = false;
            double bpm = bpmCell.toDouble(&ok);
            if (!ok) bpm = QLocale().toDouble(bpmCell.toString(), &ok);
            tracks.append(QJsonObject{{"title", title.left(256)},
                    {"artist", cell(row, artistCol).toString().left(128)},
                    {"bpm", ok && std::isfinite(bpm) && bpm > 0.0
                                    ? QJsonValue(bpm) : QJsonValue(QJsonValue::Null)}});
        }
        browserState["available"] = true;
        browserState["tracks"] = tracks;
        browserState["selected_row"] = selected >= first && selected < first + tracks.size()
                ? selected - first : -1;
        browserState["first_row"] = first;
        browserState["total_rows"] = total;
    }

    void publish() {
        QJsonArray snapshots;
        const qint64 now = clock.elapsed();
        if (now - lastAuxiliary >= 200) {
            sampleAuxiliary();
            lastAuxiliary = now;
        }
        const int count = std::min(kDecks, players->numberOfDecks());
        for (int i = 0; i < count; ++i) {
            auto& deck = decks[i];
            if (!deck.controls[0]) {
                const QString group = QStringLiteral("[Channel%1]").arg(i + 1);
                for (size_t k = 0; k < kControls.size(); ++k) {
                    deck.controls[k] = std::make_unique<ControlProxy>(group,
                            QString::fromLatin1(kControls[k]));
                }
            }
            auto* player = players->getDeckBase(i);
            const auto track = player ? player->getLoadedTrack() : TrackPointer();
            if (track != deck.track) {
                deck.track = track;
                ++deck.generation;
                deck.overview.clear();
                deck.overviewSource = nullptr;
                deck.lastOverview = -1000;
            }
            const bool loaded = track && deck.value(7) > 0.0;
            QJsonObject out{{"deck", i + 1}, {"loaded", loaded}, {"generation", deck.generation}};
            if (loaded) {
                const double duration = std::max(0.0, finiteValue(track->getDuration()) * 1000.0);
                const double position = std::clamp(deck.value(0), -1.0, 2.0) * duration;
                const QString title = track->getTitle().isEmpty()
                        ? QFileInfo(track->getLocation()).completeBaseName()
                        : track->getTitle();
                out.insert("title", title);
                out.insert("artist", track->getArtist());
                out.insert("key", track->getKeyText());
                out.insert("original_bpm", finiteValue(track->getBpm()));
                out.insert("duration_ms", duration);
                out.insert("position_ms", position);
                out.insert("bpm", deck.value(1));
                out.insert("pitch_percent", deck.value(2) * deck.value(3) * deck.value(4) * 100.0);
                out.insert("range_percent", deck.value(3) * 100.0);
                out.insert("playing", deck.value(5) > 0.0);
                out.insert("beat_distance", deck.value(6));
                const auto summary = track->getWaveformSummary();
                const bool overviewReady = summary && summary->getCompletion() > 0;
                if (overviewReady && (now - deck.lastOverview >= 1000 ||
                                             summary.data() != deck.overviewSource ||
                                             deck.overview.size() != kOverviewColumns * 4)) {
                    deck.overview = peaks(summary, kOverviewColumns, 0.0,
                            double(summary->getDataSize()) / (2.0 * kOverviewColumns));
                    deck.lastOverview = now;
                    deck.overviewSource = summary.data();
                }
                out.insert("overview_ready", overviewReady);
                if (overviewReady) {
                    out.insert("overview", QString::fromLatin1(deck.overview.toBase64()));
                }
                const auto waveform = track->getWaveform();
                const bool detailReady = detail && waveform && waveform->getCompletion() > 0 &&
                        waveform->getAudioVisualRatio() > 0.0;
                out.insert("detail_ready", detailReady);
                if (detailReady) {
                    const double framesPerSecond = track->getSampleRate().toDouble() /
                            waveform->getAudioVisualRatio();
                    const double startMs = std::floor(position / 125.0) * 125.0 - 750.0;
                    const QByteArray data = peaks(waveform, kDetailColumns,
                            startMs * framesPerSecond / 1000.0, framesPerSecond / kColumnsPerSecond);
                    out.insert("detail", QString::fromLatin1(data.toBase64()));
                    out.insert("detail_start_ms", startMs);
                    out.insert("columns_per_second", kColumnsPerSecond);
                }
            }
            snapshots.append(out);
        }
        const QJsonObject state{{"schema", 1}, {"source", "native"},
                {"session", session}, {"clock_ms", now}, {"decks", snapshots},
                {"effects", effectState}, {"browser", browserState}};
        const QByteArray json = QJsonDocument(state).toJson(QJsonDocument::Compact);
        if (json.size() < 60000) {
            // Dropping a snapshot is intentional: never wait for the renderer.
            ::sendto(fd, json.constData(), json.size(), MSG_DONTWAIT | MSG_NOSIGNAL,
                    reinterpret_cast<const sockaddr*>(&address), sizeof(address));
        }
    }
};

NumarkNvExporter::NumarkNvExporter(PlayerManager* players, EffectsManager* effects, Library* library)
        : QObject(players), m_impl(std::make_unique<Impl>(players, effects, library)) {
}

NumarkNvExporter::~NumarkNvExporter() = default;
