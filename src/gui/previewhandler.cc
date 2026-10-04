/*
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
#include "previewhandler.h"
#include "../engine/rtengine.h"
#include <gtkmm.h>

namespace art { namespace gui {
using namespace utils;


using namespace art::engine;
using namespace art::engine::procparams;

PreviewHandler::PreviewHandler(): image(nullptr), previewScale(1.)
{

    pih = new PreviewHandlerIdleHelper;
    pih->phandler = this;
    pih->destroyed = false;
    pih->pending = 0;
}

PreviewHandler::~PreviewHandler()
{
    idle_register.destroy();

    if (pih->pending) {
        pih->destroyed = true;
    } else {
        delete pih;
    }
}

//----------------previewimagelistener functions--------------------

void PreviewHandler::setImage(art::engine::IImage8 *i, double scale,
                              const art::engine::procparams::CropParams &cp)
{
    pih->pending++;

    idle_register.add([this, i, scale, cp]() -> bool {
        if (pih->destroyed) {
            if (pih->pending == 1) {
                delete pih;
            } else {
                --pih->pending;
            }

            return false;
        }

        if (pih->phandler->image) {
            IImage8 *const oldImg = pih->phandler->image;

            oldImg->getMutex().lock();
            pih->phandler->image = i;
            oldImg->getMutex().unlock();
        } else {
            pih->phandler->image = i;
        }

        pih->phandler->cropParams = cp;
        pih->phandler->previewScale = scale;
        --pih->pending;

        return false;
    });
}

void PreviewHandler::delImage(IImage8 *i)
{
    pih->pending++;

    idle_register.add([this, i]() -> bool {
        if (pih->destroyed) {
            if (pih->pending == 1) {
                delete pih;
            } else {
                --pih->pending;
            }

            return false;
        }

        if (pih->phandler->image) {
            IImage8 *oldImg = pih->phandler->image;
            oldImg->getMutex().lock();
            pih->phandler->image = nullptr;
            oldImg->getMutex().unlock();
        }

        i->free();
        pih->phandler->previewImgMutex.lock();
        pih->phandler->previewImg.clear();
        pih->phandler->previewImgMutex.unlock();

        --pih->pending;

        return false;
    });
}

void PreviewHandler::imageReady(const art::engine::procparams::CropParams &cp)
{
    pih->pending++;

    idle_register.add([this, cp]() -> bool {
        if (pih->destroyed) {
            if (pih->pending == 1) {
                delete pih;
            } else {
                --pih->pending;
            }

            return false;
        }

        pih->phandler->previewImgMutex.lock();
        pih->phandler->previewImg = Gdk::Pixbuf::create_from_data(
            pih->phandler->image->getData(), Gdk::COLORSPACE_RGB, false, 8,
            pih->phandler->image->getWidth(), pih->phandler->image->getHeight(),
            3 * pih->phandler->image->getWidth());
        pih->phandler->previewImgMutex.unlock();

        pih->phandler->cropParams = cp;
        pih->phandler->previewImageChanged();
        --pih->pending;

        return false;
    });
}

Glib::RefPtr<Gdk::Pixbuf> PreviewHandler::getRoughImage(int x, int y, int w,
                                                        int h, double zoom)
{
    MyMutex::MyLock lock(previewImgMutex);

    Glib::RefPtr<Gdk::Pixbuf> resPixbuf;

    if (previewImg) {
        double totalZoom = zoom * previewScale;

        if (w > previewImg->get_width() * totalZoom) {
            w = image->getWidth() * totalZoom;
        }

        if (h > previewImg->get_height() * totalZoom) {
            h = image->getHeight() * totalZoom;
        }

        x *= zoom;
        y *= zoom;

        w = art::engine::LIM<int>(w, 0,
                               int(previewImg->get_width() * totalZoom) - x);
        h = art::engine::LIM<int>(h, 0,
                               int(previewImg->get_height() * totalZoom) - y);

        resPixbuf = Gdk::Pixbuf::create(Gdk::COLORSPACE_RGB, false, 8, w, h);
        previewImg->scale(resPixbuf, 0, 0, w, h, -x, -y, totalZoom, totalZoom,
                          Gdk::INTERP_NEAREST);
    }

    return resPixbuf;
}

Glib::RefPtr<Gdk::Pixbuf>
PreviewHandler::getRoughImage(int desiredW, int desiredH, double &zoom_)
{
    MyMutex::MyLock lock(previewImgMutex);

    Glib::RefPtr<Gdk::Pixbuf> resPixbuf;

    if (previewImg) {
        double zoom1 =
            (double)max(desiredW, 20) /
            previewImg
                ->get_width(); // too small values lead to extremely increased
                               // processing time in scale function, Issue 2783
        double zoom2 =
            (double)max(desiredH, 20) / previewImg->get_height(); // ""
        double zoom = zoom1 < zoom2 ? zoom1 : zoom2;

        resPixbuf = Gdk::Pixbuf::create(Gdk::COLORSPACE_RGB, false, 8,
                                        image->getWidth() * zoom,
                                        image->getHeight() * zoom);
        previewImg->scale(resPixbuf, 0, 0, previewImg->get_width() * zoom,
                          previewImg->get_height() * zoom, 0, 0, zoom, zoom,
                          Gdk::INTERP_BILINEAR);
        zoom_ = zoom / previewScale;
    }

    return resPixbuf;
}

Glib::RefPtr<Gdk::Pixbuf> PreviewHandler::getPreviewImage(int max_size)
{
    MyMutex::MyLock lock(previewImgMutex);

    if (!previewImg || max_size < 1) {
        return Glib::RefPtr<Gdk::Pixbuf>();
    }
    const int w = previewImg->get_width();
    const int h = previewImg->get_height();
    const int longest = max(w, h);
    if (longest <= max_size) {
        // a deep copy: previewImg shares the engine's pixel buffer
        return previewImg->copy();
    }
    const double s = double(max_size) / longest;
    return previewImg->scale_simple(max(1, int(w * s + 0.5)),
                                    max(1, int(h * s + 0.5)),
                                    Gdk::INTERP_BILINEAR);
}

void PreviewHandler::previewImageChanged()
{

    for (std::list<PreviewListener *>::iterator i = listeners.begin();
         i != listeners.end(); ++i) {
        (*i)->previewImageChanged();
    }
}


} } // namespace art::gui
