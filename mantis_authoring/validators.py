# Copyright (c) Siemens AG, 2015
#
# This file is part of MANTIS.  MANTIS is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either version 2
# of the License, or(at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import sdv

class Basic_STIX_Validator:
    validate_xml = True

    #version of the STIX document, if None stix_validator tries to extract the version from the xml to validate
    #if you make use of non-bundled schemas or the xsi:schemaLocation attribute this value will be ignored
    #e.g. stix_version = '1.2'
    stix_version = None

    #if you want to validate the xml against non-bundled schemas you can define a path to a folder containing them
    #e.g. schemas_path = "/path/to/schemas/"
    schemas_path = None

    #if True, the validator makes use of the xsi:schemaLocation attribute within the stix xml document
    schemaloc = False

    #if True, the validator will perform a validation based on http://stixproject.github.io/documentation/suggested-practices/
    #this validation process is still under active development, not all STIX Best Practices are covered
    validate_best_practices = False

    #if True, the vdalidator will perform a validation agaist a STIX Profile: http://stixproject.github.io/documentation/profiles/
    #of course a profile path has to be specified: profile_path = "/path/to/stix/profile.xlsx"
    #sample profile STIX 1.2 https://stix.mitre.org/language/profiles/samples/stix_1.2_sample_indicator_sharing_profile_r1.xlsx
    validate_profile = False
    profile_path = None

    result = None

    @property
    def is_valid(self):
        return self.result.is_valid

    @property
    def errors(self):
        return self.result.errors

    @property
    def get_error_class(self):
        return self.result.errors[0].__class__.__name__

    def __init__(self, xml_to_validate):
        if self.validate_xml:
            self.result = sdv.validate_xml(xml_to_validate, self.stix_version, self.schemas_path, self.schemaloc)
        if self.result.is_valid and self.validate_best_practices:
            self.result = sdv.validate_best_practices(xml_to_validate, self.stix_version)
        if self.result.is_valid and self.validate_profile and self.profile:
            self.result = sdv.validate_profile(xml_to_validate, self.profile_path)


class STIX_Validator(Basic_STIX_Validator):
    stix_version = '1.2'