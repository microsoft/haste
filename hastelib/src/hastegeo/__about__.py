# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
# Local/editable installs intentionally use a development marker. CI supplies
# HASTE_SET_VERSION when building a release wheel, and the build hook stamps
# that exact PEP 440 version into the wheel's bundled copy of this file.
__version__ = "0.0.0+local"
