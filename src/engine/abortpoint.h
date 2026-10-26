/* -*- C++ -*-
 *
 *  This file is part of ART.
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

/**
 * Abandoning a preview update that a newer edit has made stale.
 *
 * A running update owns an AbortScope (improcfun.h), which publishes a probe
 * on its thread.  Code deep inside a tool calls abortPoint() from its serial
 * driver code to unwind with Cancelled, and may copy the probe (via
 * currentAbortProbe()) to poll it from an OpenMP region -- there it must only
 * *skip* work, never throw, and call abortPoint() after the region.
 *
 * Everything is inert on threads with no AbortScope: export, thumbnails, the
 * coordinator's own preview chain, and OpenMP workers.
 */

#include <atomic>
#include <cstdint>

namespace art { namespace engine {

/// Thrown by abortPoint()/ImProcFunctions::throwIfAborted().  Deliberately not
/// derived from std::exception: some tools catch that and carry on.
struct Cancelled {};

class AbortProbe {
public:
    AbortProbe() = default;
    AbortProbe(const std::atomic<uint64_t> *gen, uint64_t start):
        gen_(gen), start_(start) {}

    bool operator()() const
    {
        return gen_ && gen_->load(std::memory_order_acquire) != start_;
    }

private:
    const std::atomic<uint64_t> *gen_ = nullptr;
    uint64_t start_ = 0;
};

inline const AbortProbe *&abortProbeSlot()
{
    static thread_local const AbortProbe *p = nullptr;
    return p;
}

/// The probe of the update running on this thread (inert if none).
inline AbortProbe currentAbortProbe()
{
    const AbortProbe *p = abortProbeSlot();
    return p ? *p : AbortProbe();
}

/// Throw Cancelled if the update running on this thread is stale.  Serial
/// code only, and only where nothing is left half-done that the caller's
/// own redo bookkeeping does not cover.
inline void abortPoint()
{
    const AbortProbe *p = abortProbeSlot();
    if (p && (*p)()) {
        throw Cancelled();
    }
}

}} // namespace art::engine
