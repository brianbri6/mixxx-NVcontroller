// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <QObject>
#include <memory>

class PlayerManager;
class EffectsManager;
class Library;

// GUI-thread, read-only telemetry. Enabled only by BITEDJ_NV_SOCKET.
// USB output belongs to the separate, bounded Python service.
class NumarkNvExporter final : public QObject {
  public:
    NumarkNvExporter(PlayerManager* players, EffectsManager* effects, Library* library);
    ~NumarkNvExporter() override;

  private:
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};
