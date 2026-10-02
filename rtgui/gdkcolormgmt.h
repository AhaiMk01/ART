// -*- C++ -*-

#pragma once

#include "../rtengine/settings.h"
#include <gtkmm.h>

namespace art {

void gdk_set_monitor_profile(GdkWindow *window,
                             art::engine::Settings::StdMonitorProfile prof);

} // namespace art
