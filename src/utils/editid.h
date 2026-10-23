/* -*- C++ -*-
 *  This file is part of ART.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
 *  Copyright (c) 2018-2026 Alberto Griggio <alberto.griggio@gmail.com>
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

namespace art { namespace utils {


/// @brief List of pipette editing operation
enum EditUniqueID : unsigned int {
    EUID_None, /// special value (default)

    EUID_DehazeStrength,
    EUID_ToneCurve1,
    EUID_ToneCurve2,
    EUID_ToneCurveSaturation,
    EUID_ToneCurveSaturation2,
    EUID_Lab_LCurve,
    EUID_Lab_aCurve,
    EUID_Lab_bCurve,
    EUID_RGB_R,
    EUID_RGB_G,
    EUID_RGB_B,
    EUID_HSL_H,
    EUID_HSL_S,
    EUID_HSL_V,
    EUID_ColorCorrection_Wheel,
    EUID_ColorCorrection_Wheel_Jzazbz,
    EUID_Masks_H1,
    EUID_Masks_C1,
    EUID_Masks_L1,
    EUID_Masks_H2,
    EUID_Masks_C2,
    EUID_Masks_L2,
    EUID_Masks_H3,
    EUID_Masks_C3,
    EUID_Masks_L3,
    EUID_Masks_H4,
    EUID_Masks_C4,
    EUID_Masks_L4,
    EUID_Masks_DE1, // color correction
    EUID_Masks_DE2, // local contrast
    EUID_Masks_DE3, // smoothing
    EUID_Masks_DE4  // texture boost
};

/// IDs come in two namespaces, told apart by the most significant bit. The
/// built-in IDs above have it clear; IDs defined by CTL scripts have it set.
/// For a CTL ID, clearing the bit (ctlEditValue) gives a payload laid out as:
///   bits  0-15: curve id (index in the script's @ART-pipette list)
///   bits 16-29: region index (ColorCorrection; 0 for Film Simulation)
///   bit  30   : EUID_CTL_COLORCORRECTION_TAG, set for ColorCorrection
constexpr unsigned int EUID_CTL_FLAG = 1u << 31;
constexpr unsigned int EUID_CTL_COLORCORRECTION_TAG = 1u << 30;
constexpr unsigned int EUID_CTL_CURVE_MASK = 0xffffu;
constexpr unsigned int EUID_CTL_REGION_SHIFT = 16;

inline bool isCTLEditID(EditUniqueID id)
{
    return (static_cast<unsigned int>(id) & EUID_CTL_FLAG) != 0;
}

inline EditUniqueID ctlEditID(unsigned int value)
{
    return static_cast<EditUniqueID>(value | EUID_CTL_FLAG);
}

inline unsigned int ctlEditValue(EditUniqueID id)
{
    return static_cast<unsigned int>(id) & ~EUID_CTL_FLAG;
}

/// payload base (everything but the curve id) for a tool's curves
inline unsigned int ctlEditBase(bool colorcorrection, unsigned int region = 0)
{
    return (colorcorrection ? EUID_CTL_COLORCORRECTION_TAG : 0u) |
        (region << EUID_CTL_REGION_SHIFT);
}

inline unsigned int ctlEditBase(EditUniqueID id)
{
    return ctlEditValue(id) & ~EUID_CTL_CURVE_MASK;
}

inline int ctlEditCurve(EditUniqueID id)
{
    return static_cast<int>(ctlEditValue(id) & EUID_CTL_CURVE_MASK);
}

/// @brief Editing mechanisms
//  TODO: Look out if it has to be a bitfield to allow both mechanisms at a time
enum EditType {
    ET_PIPETTE, /// Will trigger dedicated methods; can have a geometry list to
                /// be displayed, but without "mouse over" capabilities
    ET_OBJECTS  /// The objects are geometrical widgets with "mouse over"
                /// capabilities
};

/// @brief Buffer type for ET_PIPETTE type editing
enum BufferType {
    BT_IMAGEFLOAT,       /// Imagefloat buffer type (3 channels of float values)
    BT_LABIMAGE,         /// LabImage buffer type (3 channels of float values)
    BT_SINGLEPLANE_FLOAT /// All purpose, 1 channel buffer of float values
};

/// @brief Number of object to be handled (for optimization purpose)
enum ObjectMode {
    OM_255,  /// less or equal than 255 objects
    OM_65535 /// less or equal than 65535 objects
};


} } // namespace art::utils
