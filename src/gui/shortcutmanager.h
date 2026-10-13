/** -*- C++ -*-
 *
 *  This file is part of ART.
 *
 *  Copyright (c) 2020 Alberto Griggio <alberto.griggio@gmail.com>
 *
 *  ART is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  ART is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with ART.  If not, see <http://www.gnu.org/licenses/>.
 */

#pragma once

#include "guiutils.h"
#include <string>
#include <unordered_map>

namespace art { namespace gui {


class RTWindow;
class Adjuster;
class FoldableToolPanel;

class ToolShortcutManager {
public:
    ToolShortcutManager(RTWindow *parent);
    ~ToolShortcutManager();
    /// Register `adjuster` of `tool` as the target of the held-key shortcut
    /// `action_id` (e.g. "tool.exposure.compensation"). Which key that is
    /// comes from the ShortcutsManager.
    void addShortcut(const std::string &action_id, FoldableToolPanel *tool,
                     Adjuster *adjuster);
    void reset(bool clear);
    bool keyPressed(GdkEventKey *event);
    bool keyReleased(GdkEventKey *event);
    bool scrollPressed(GdkEventScroll *event);
    bool shouldHandleScroll() const;
    void showHelp();

private:
    void doit(int direction, int speed = 1);

    RTWindow *parent_;
    std::unordered_map<std::string, std::pair<FoldableToolPanel *, Adjuster *>>
        action_map_;
    std::string cur_action_; // the shortcut being held, "" if none
    FoldableToolPanel *cur_tool_;
    Adjuster *cur_adjuster_;
    sigc::connection conn_;
};


} } // namespace art::gui
