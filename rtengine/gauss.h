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

#include <vector>

namespace art { namespace engine {

enum eGaussType { GAUSS_STANDARD, GAUSS_MULT, GAUSS_DIV };

void gaussianBlur(float **src, float **dst, const int W, const int H,
                  const double sigma, float *buffer = nullptr,
                  eGaussType gausstype = GAUSS_STANDARD,
                  float **buffer2 = nullptr);

}} // namespace art::engine


#ifdef ART_USE_VULKAN

namespace art { namespace engine {

namespace gpu {

class Pass;
class Buffer;

namespace ops {

/* Truncated, normalised Gaussian.  3 sigma captures ~99.7% of the kernel; the
 * remaining tail is below float precision against the normalisation.
 * Shared with ipsmoothing.cc, which needs the same weights to build its own
 * device-resident Gaussian blur. */
int gaussRadius(double sigma);
void gaussWeights(double sigma, int radius, std::vector<float> &out);

/* Run the two separable Gaussian passes over an already device-resident
 * W x H plane pair -- a is input and output, b is scratch, weights must
 * already hold gaussWeights(sigma, radius, ...). */
bool gaussianBlurPasses(Pass &pass, Buffer &a, Buffer &b, Buffer &weights,
                        int W, int H, int radius);

} // namespace ops
} // namespace gpu
}} // namespace art::engine

#endif // ART_USE_VULKAN
