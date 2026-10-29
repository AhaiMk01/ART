/* -*- C++ -*-
 *  This file is part of ART.
 *
 *  Copyright (c) 2018 Jean-Christophe FRISCH <natureh.510@gmail.com>
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

#include "rtscalable.h"
#include <gtkmm/image.h>

namespace art { namespace gui {


/**
 * @brief A derived class of Gtk::Image in order to handle theme-related icon
 * sets.
 */
class RTSurface: public RTScalable {
    void changeImage(Glib::ustring imageName, const std::string &color);

public:
    Cairo::RefPtr<Cairo::ImageSurface> surface;

    RTSurface();
    RTSurface(const RTSurface &other);
    /** @param color if not empty, replaces the theme svg color */
    RTSurface(Glib::ustring fileName,
              Glib::ustring rtlFileName = Glib::ustring(),
              const std::string &color = "");

    // void setImage(Glib::ustring fileName,
    //               Glib::ustring rtlFileName = Glib::ustring());
    int getWidth() const;
    int getHeight() const;
    bool hasSurface() const;

    // static void init();
    // static void updateImages();

    // void from(Glib::RefPtr<RTSurface> other);
};


} } // namespace art::gui
