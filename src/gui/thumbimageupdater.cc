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

#include <atomic>
#include <map>
#include <set>

#include <gtkmm.h>

#include "thumbimageupdater.h"

#include "guiutils.h"
#include "options.h"
#include "../utils/threadutils.h"

#include "../engine/threadpool.h"

#ifdef _OPENMP
#include <omp.h>
#endif

namespace art { namespace gui {


#define DEBUG(format, args...)
// #define DEBUG(format,args...) printf("ThumbImageUpdate::%s: " format "\n",
// __FUNCTION__, ## args)

class ThumbImageUpdater::Impl: public art::engine::NonCopyable {
public:
    struct Job {
        Job(ThumbBrowserEntryBase *tbe, bool *priority, bool upgrade,
            ThumbImageUpdateListener *listener)
            : tbe_(tbe),
              /*pparams_(pparams),
              height_(height), */
              priority_(priority), upgrade_(upgrade), listener_(listener)
        {
        }

        Job()
            : tbe_(nullptr), priority_(nullptr), upgrade_(false),
              listener_(nullptr)
        {
        }

        ThumbBrowserEntryBase *tbe_;
        /*art::engine::procparams::ProcParams pparams_;
        int height_;*/
        bool *priority_;
        bool upgrade_;
        ThumbImageUpdateListener *listener_;
    };

    typedef std::list<Job> JobList;

    Impl(): active_(0) {}

    std::mutex mutex_;

    JobList jobs_;

    // number of jobs being processed right now, in total and per listener
    // (running_ is protected by mutex_)
    std::atomic<unsigned int> active_;
    std::map<ThumbImageUpdateListener *, unsigned int> running_;

    // notified whenever a job finishes
    std::condition_variable inactive_;

    void processNextJob()
    {
        Job j;

        {
            std::unique_lock<std::mutex> lock(mutex_);

            // nothing to do; could be jobs have been removed
            if (jobs_.empty()) {
                DEBUG("processing: nothing to do (%d)", jobs_.empty());
                return;
            }

            JobList::iterator i;

            // see if any priority jobs exist
            for (i = jobs_.begin(); i != jobs_.end(); ++i) {
                if (*(i->priority_)) {
                    DEBUG("processing(priority) %s",
                          i->tbe_->thumbnail->getFileName().c_str());
                    break;
                }
            }

            // see if any none upgrade jobs exist
            if (i == jobs_.end()) {
                for (i = jobs_.begin(); i != jobs_.end(); ++i) {
                    if (!i->upgrade_) {
                        DEBUG("processing(not-upgrade) %s",
                              i->tbe_->thumbnail->getFileName().c_str());
                        break;
                    }
                }
            }

            // if none, then use first
            if (i == jobs_.end()) {
                i = jobs_.begin();
                DEBUG("processing(first) %s",
                      i->tbe_->thumbnail->getFileName().c_str());
            }

            // copy found job
            j = *i;

            // remove so not run again
            jobs_.erase(i);
            DEBUG("%d job(s) remaining", int(jobs_.size()));

            ++active_;
            ++running_[j.listener_];
        }

        // unlock and do processing; will relock on block exit, then call
        // listener
        double scale = 1.0;
        art::engine::IImage8 *img = nullptr;
        Thumbnail *thm = j.tbe_->thumbnail;

        DEBUG("working on %s", thm->getFileName().c_str());

        if (j.upgrade_ && thm->isQuick()) {
            if (true) { // thm->isQuick() ) {
                DEBUG("   trying to upgrade\n");
                img = thm->upgradeThumbImage(thm->getProcParams(),
                                             j.tbe_->getPreviewHeight(), scale);
            }
        } else {
            DEBUG("   trying to process\n");
            img = thm->processThumbImage(thm->getProcParams(),
                                         j.tbe_->getPreviewHeight(), scale);
        }

        if (img) {
            DEBUG("pushing image %s", thm->getFileName().c_str());
            j.listener_->updateImage(img, scale, thm->getProcParams().crop);
        }

        {
            // updating the counters and notifying with the mutex held
            // guarantees that a waiter in removeJobs()/removeAllJobs(), which
            // checks them with the mutex held, is either already waiting or
            // sees the new state
            std::unique_lock<std::mutex> lock(mutex_);
            --active_;
            auto it = running_.find(j.listener_);
            if (it != running_.end() && --it->second == 0) {
                running_.erase(it);
            }
            inactive_.notify_all();
        }
    }
};

ThumbImageUpdater *ThumbImageUpdater::getInstance()
{
    static ThumbImageUpdater instance_;
    return &instance_;
}

ThumbImageUpdater::ThumbImageUpdater(): impl_(new Impl()) {}

ThumbImageUpdater::~ThumbImageUpdater() { delete impl_; }

void ThumbImageUpdater::add(ThumbBrowserEntryBase *tbe, bool *priority,
                            bool upgrade, ThumbImageUpdateListener *l)
{
    // nobody listening?
    if (l == nullptr) {
        return;
    }

    std::unique_lock<std::mutex> lock(impl_->mutex_);

    // look up if an older version is in the queue
    Impl::JobList::iterator i(impl_->jobs_.begin());

    for (; i != impl_->jobs_.end(); ++i) {
        if (i->tbe_ == tbe && i->listener_ == l && i->upgrade_ == upgrade) {
            DEBUG("updating job %s", tbe->filename.c_str());
            // we have one, update queue entry, will be picked up by thread when
            // processed
            /*i->pparams_ = params;
            i->height_ = height; */
            i->priority_ = priority;
            return;
        }
    }

    // create a new job and append to queue
    DEBUG("queueing job %s", tbe->filename.c_str());
    impl_->jobs_.push_back(Impl::Job(tbe, priority, upgrade, l));

    DEBUG("adding run request %s", tbe->filename.c_str());
    art::engine::ThreadPool::add_task(
        art::engine::ThreadPool::Priority::LOW,
        sigc::mem_fun(*impl_, &ThumbImageUpdater::Impl::processNextJob));
}

void ThumbImageUpdater::removeJobs(ThumbImageUpdateListener *listener)
{
    DEBUG("removeJobs(%p)", listener);

    {
        std::unique_lock<std::mutex> lock(impl_->mutex_);

        for (Impl::JobList::iterator i(impl_->jobs_.begin());
             i != impl_->jobs_.end();) {
            if (i->listener_ == listener) {
                DEBUG("erasing specific job");
                Impl::JobList::iterator e(i++);
                impl_->jobs_.erase(e);
            } else {
                ++i;
            }
        }
    }

    // Wait for this listener's own jobs that are running right now. Not for
    // all running jobs: while the queue is deep there is always some job
    // running (for any other listener), so waiting for that would block the
    // caller (the GUI thread) until the queue is nearly empty.
    {
        std::unique_lock<std::mutex> lock(impl_->mutex_);
        impl_->inactive_.wait(lock, [this, listener]() {
            return impl_->running_.find(listener) == impl_->running_.end();
        });
    }
}

void ThumbImageUpdater::removeAllJobs()
{
    DEBUG("stop");

    // The queue is emptied first, so no new job can start and the wait for
    // the running ones is bounded by the longest of them.
    std::unique_lock<std::mutex> lock(impl_->mutex_);
    impl_->jobs_.clear();
    impl_->inactive_.wait(lock, [this]() { return impl_->active_ == 0; });
}


} } // namespace art::gui
