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

#include "shortcutmanager.h"
#include "../utils/multilangmgr.h"
#include "options.h"
#include "rtwindow.h"
#include "shortcutsmanager.h"
#include "toolpanel.h"

#include <map>
#include <vector>

namespace art { namespace gui {
using namespace utils;


extern Options options;

namespace {

enum {
    DIRECTION_ZERO = 0,
    DIRECTION_DOWN = -1,
    DIRECTION_UP = 1,
    DIRECTION_INITIAL = 2
};

} // namespace


ToolShortcutManager::ToolShortcutManager(RTWindow *parent)
    : parent_(parent), cur_tool_(nullptr), cur_adjuster_(nullptr)
{
    auto sm = ShortcutsManager::getInstance();
    sm->bind(this, "tool.help", [this](GdkEventKey *) {
        showHelp();
        return true;
    });
    // +/-/reset while a key is held (the dispatch is only asked then)
    const auto value = [this, sm](const char *id, int direction) {
        sm->bind(this, id, [this, direction](GdkEventKey *) {
            doit(direction);
            return true;
        });
    };
    value("tool.value_up", DIRECTION_UP);
    value("tool.value_down", DIRECTION_DOWN);
    value("tool.value_zero", DIRECTION_ZERO);
    value("tool.value_initial", DIRECTION_INITIAL);
}

ToolShortcutManager::~ToolShortcutManager()
{
    ShortcutsManager::getInstance()->unbindOwner(this);
    if (conn_.connected()) {
        conn_.disconnect();
    }
}

void ToolShortcutManager::reset(bool clear)
{
    cur_action_.clear();
    cur_tool_ = nullptr;
    cur_adjuster_ = nullptr;
    if (conn_.connected()) {
        conn_.disconnect();
    }
    if (clear) {
        action_map_.clear();
    }
}

void ToolShortcutManager::addShortcut(const std::string &action_id,
                                      FoldableToolPanel *tool,
                                      Adjuster *adjuster)
{
    action_map_[action_id] = std::make_pair(tool, adjuster);

    // pressing the key arms the adjuster (and key repeat keeps it so)
    ShortcutsManager::getInstance()->bind(
        this, action_id, [this, action_id](GdkEventKey *) {
            auto it = action_map_.find(action_id);
            if (it == action_map_.end()) {
                return false; // removed by reset(true)
            }
            if (cur_action_ != action_id) {
                cur_action_ = action_id;
                cur_tool_ = it->second.first;
                cur_adjuster_ = it->second.second;
            }
            return true;
        });
}

namespace {

bool has_modifiers(GdkEventKey *event)
{
    return event->state &
           (ShortcutsManager::getInstance()->primaryMask() |
            GDK_CONTROL_MASK | GDK_MOD1_MASK);
}

} // namespace

bool ToolShortcutManager::keyPressed(GdkEventKey *event)
{
    auto sm = ShortcutsManager::getInstance();

    if (shouldHandleScroll() &&
        sm->dispatch(event, ShortcutPhase::After, {{"tool-value", this}})) {
        return true;
    }

    if (sm->dispatch(event, ShortcutPhase::After, {{"tool", this}})) {
        return true;
    }

    // any other key (without Ctrl/Alt/Cmd) lets go of the adjuster
    if (has_modifiers(event)) {
        return false;
    }
    return keyReleased(event);
}

bool ToolShortcutManager::keyReleased(GdkEventKey *event)
{
    // the release of +/-/reset keys while an adjuster is held is not ours to
    // act on, but must not let go of it
    if (shouldHandleScroll() &&
        ShortcutsManager::getInstance()->matches(event, ShortcutPhase::After,
                                                 "tool-value")) {
        return true;
    }

    cur_action_.clear();
    cur_tool_ = nullptr;
    cur_adjuster_ = nullptr;

    return false;
}

bool ToolShortcutManager::scrollPressed(GdkEventScroll *event)
{
    if (shouldHandleScroll()) {
        if (conn_.connected()) {
            conn_.disconnect();
        }

        int dir =
            event->direction == GDK_SCROLL_DOWN ? DIRECTION_DOWN : DIRECTION_UP;
        doit(dir, options.adjuster_shortcut_scrollwheel_factor);
        return true;
    }
    return false;
}

bool ToolShortcutManager::shouldHandleScroll() const
{
    return (!cur_action_.empty() && cur_tool_ != nullptr &&
            cur_adjuster_ != nullptr);
}

void ToolShortcutManager::doit(int direction, int speed)
{
    cur_tool_->disableListener();
    cur_tool_->setEnabled(true);
    if (direction == DIRECTION_ZERO) {
        cur_adjuster_->resetValue(false);
    } else if (direction == DIRECTION_INITIAL) {
        cur_adjuster_->resetValue(true);
    } else {
        cur_adjuster_->setValue(cur_adjuster_->getValue() +
                                direction * cur_adjuster_->getStepValue() *
                                    speed);
    }
    Glib::ustring msg = cur_tool_->getUILabel() + ": " +
                        cur_adjuster_->getLabel() + " = " +
                        cur_adjuster_->getTextValue();
    parent_->showInfo(msg, 0.0);

    FoldableToolPanel *tool = cur_tool_;
    Adjuster *adjuster = cur_adjuster_;
    const auto doit = [tool, adjuster]() -> bool {
        tool->enableListener();
        adjuster->forceNotifyListener();
        return false;
    };
    conn_ = Glib::signal_timeout().connect(sigc::slot<bool>(doit),
                                           options.adjusterMaxDelay);
}

void ToolShortcutManager::showHelp()
{
    Glib::ustring msg = M("TOOL_SHORTCUT_HELP_HEADER");
    std::map<Glib::ustring, std::vector<Glib::ustring>> helpmap;
    for (auto &p : action_map_) {
        auto key = ShortcutsManager::getInstance()->label(p.first);
        if (key.empty()) {
            continue; // disabled
        }
        auto header = p.second.first->getUILabel();
        auto value = key + ": " + p.second.second->getLabel();
        helpmap[header].push_back(value);
    }

    Glib::ustring pad(10, ' ');
    for (auto &p : helpmap) {
        msg += "\n";
        msg += p.first;
        Glib::ustring headpad(p.first.size() + 2, ' ');
        auto &v = p.second;
        std::sort(v.begin(), v.end());
        for (size_t i = 0; i < v.size(); ++i) {
            msg += "\n" + pad + v[i];
        }
    }

    parent_->showInfo(msg, options.error_message_duration);
}


} } // namespace art::gui
