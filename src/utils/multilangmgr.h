/* -*- C++ -*-
 *
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
 *
 *  RawTherapee is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  RawTherapee is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with RawTherapee.  If not, see <http://www.gnu.org/licenses/>.
 */
#pragma once

#include <map>
#include <string>
#include <vector>

#include <functional>
#include <glibmm/ustring.h>

namespace art { namespace utils {


class MultiLangMgr {
public:
    MultiLangMgr();

    void load(const Glib::ustring &language,
              const std::vector<Glib::ustring> &fnames);
    Glib::ustring getStr(const std::string &key) const;

    /// Strings may contain "%shortcut(action.id)%", which is replaced by what
    /// the provider returns for the id: the key currently bound to that
    /// action, so that tooltips follow the OS conventions and the user's
    /// customisation. Without a provider the text is left as it is.
    using ShortcutLabeler = std::function<Glib::ustring(const std::string &)>;
    void setShortcutLabeler(ShortcutLabeler f) { shortcut_labeler_ = std::move(f); }

    /// "%primary%" in a string becomes this: the name of the OS-convention
    /// modifier ("Ctrl", or Cmd on macOS), for "%primary%-click" and the like.
    void setPrimaryModifierName(const Glib::ustring &name) { primary_name_ = name; }
    static bool isOSLanguageDetectSupported();
    static Glib::ustring getOSUserLanguage();

private:
    std::map<std::string, Glib::ustring> translations;
    ShortcutLabeler shortcut_labeler_;
    Glib::ustring primary_name_;
};

extern MultiLangMgr langMgr;

inline Glib::ustring M(const std::string &key) { return langMgr.getStr(key); }


} } // namespace art::utils
