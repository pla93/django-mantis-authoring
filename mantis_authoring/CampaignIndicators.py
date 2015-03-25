#!/usr/bin/python
# -*- coding: utf-8 -*-

#
# Copyright (c) Siemens AG, 2014
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


import os, datetime, tempfile, importlib, json, pytz, copy, hashlib
from lxml import etree
from StringIO import StringIO
from base64 import b64decode
from uuid import uuid4
from querystring_parser import parser

from django import forms
from django.conf import settings
from django.core.cache import caches
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.templatetags.static import static
from django.views.generic import View
from django.views.generic.edit import FormView
from django.http import HttpResponse
from django.utils.html import conditional_escape


import cybox.utils
from cybox.core import Observable, Observables, Object
from cybox.common import String, Time, ToolInformation, ToolInformationList

import stix.utils
from stix.core import STIXPackage, STIXHeader
from stix.common.kill_chains import KillChainPhase
from stix.common import InformationSource, Confidence, Identity, Activity, DateTimeWithPrecision, StructuredText as StixStructuredText, VocabString as StixVocabString
from stix.common.identity import RelatedIdentities
from stix.indicator import Indicator
from stix.extensions.test_mechanism.open_ioc_2010_test_mechanism import OpenIOCTestMechanism
from stix.extensions.test_mechanism.snort_test_mechanism import SnortTestMechanism
from stix.extensions.marking.tlp import TLPMarkingStructure
from stix.bindings.extensions.marking.tlp import TLPMarkingStructureType
from stix.campaign import Campaign, Names, AssociatedCampaigns, Attribution

# 'Name' has been removed in STIX 1.1.1
try:
    from stix.campaign import VocabString as Name
except:
    from stix.campaign import Name

from stix.threat_actor import ThreatActor, AssociatedActors
from stix.data_marking import Marking, MarkingSpecification

from mantis_stix_importer.importer import STIX_Import
from mantis_stix_importer.templatetags.mantis_stix_importer_tags import get_StixIcon
from dingos import DINGOS_DEFAULT_ID_NAMESPACE_URI, DINGOS_TEMPLATE_FAMILY
from dingos.view_classes import BasicJSONView
from dingos.models import IdentifierNameSpace
from dingos_authoring.view_classes import BasicProcessingView, AuthoringMethodMixin
from dingos_authoring.models import AuthoredData
from .view_classes import BasicSTIXPackageTemplateView

from dingos.core.utilities import dict_map


FORM_VIEW_NAME = 'url.mantis_authoring.transformers.stix.campaign_indicators'

def escape_descriptions(path,v):
    if 'description' in path[-1]:
        if isinstance(v,basestring):
            return conditional_escape(v)
        else:
            return v
    else:
        return v


class FormView(BasicSTIXPackageTemplateView):

    template_name = 'mantis_authoring/%s/CampaignIndicators.html' % DINGOS_TEMPLATE_FAMILY

    title = 'Campaign Indicator'

    """
    Classes describe front-end elements. Element properties then show up in the resulting JSON as properties.
    Properties with a leading 'I_' will not be converted to JSON
    """



    class StixThreatActor(forms.Form):
        CONFIDENCE_TYPES = (
            ('High', 'High'),
            ('Medium', 'Medium'),
            ('Low', 'Low'),
            ('None', 'None'),
            ('Unknown', 'Unknown')
        )
        object_type = forms.CharField(initial="ThreatActor", widget=forms.HiddenInput)
        I_object_display_name = forms.CharField(initial="Threat Actor", widget=forms.HiddenInput)
        I_icon =  forms.CharField(initial=get_StixIcon('ThreatActor', 'stix.mitre.org'), widget=forms.HiddenInput)
        identity_name = forms.CharField(max_length=1024, help_text="*required", required=True)
        identity_aliases = forms.CharField(widget=forms.Textarea(attrs={'placeholder': 'Line by line aliases of this threat actor'}), required=False, )
        title = forms.CharField(max_length=1024)
        description = forms.CharField(widget=forms.Textarea, required=False)
        #confidence = forms.ChoiceField(choices=CONFIDENCE_TYPES, required=False, initial="med")
        #information_source = forms.CharField(max_length=1024)


    class StixThreatActorReference(forms.Form):
        object_type = forms.CharField(initial="ThreatActorReference", widget=forms.HiddenInput)
        I_object_display_name = forms.CharField(initial="Threat Actor Reference", widget=forms.HiddenInput)
        I_icon =  forms.CharField(initial=get_StixIcon('ThreatActor', 'stix.mitre.org'), widget=forms.HiddenInput)
        object_id =  forms.CharField(initial='', widget=forms.HiddenInput)
        label =  forms.CharField(initial='', widget=forms.HiddenInput)

    class StixCampaign(forms.Form):
        STATUS_TYPES = (
            ('Success', 'Success'),
            ('Fail', 'Fail'),
            ('Error', 'Error'),
            ('Complete/Finish', 'Complete/Finish'),
            ('Pending', 'Pending'),
            ('Ongoing', 'Ongoing'),
            ('Unknown', 'Unknown')
        )
        CONFIDENCE_TYPES = (
            ('High', 'High'),
            ('Medium', 'Medium'),
            ('Low', 'Low'),
            ('None', 'None'),
            ('Unknown', 'Unknown')
        )
        object_type = forms.CharField(initial="Campaign", widget=forms.HiddenInput)
        I_object_display_name = forms.CharField(initial="Campaign", widget=forms.HiddenInput)
        I_icon =  forms.CharField(initial=get_StixIcon('Campaign', 'stix.mitre.org'), widget=forms.HiddenInput)
        name = forms.CharField(max_length=1024, help_text="*required", required=True)
        title = forms.CharField(max_length=1024)
        description = forms.CharField(widget=forms.Textarea, required=False)
        status = forms.ChoiceField(choices=STATUS_TYPES, required=False, initial="Unknown")
        #activity_timestamp_from = forms.CharField(max_length=1024)
        #activity_timestamp_to = forms.CharField(max_length=1024)
        #confidence = forms.ChoiceField(choices=CONFIDENCE_TYPES, required=False, initial="med")

    class StixCampaignReference(forms.Form):
        object_type = forms.CharField(initial="CampaignReference", widget=forms.HiddenInput)
        I_object_display_name = forms.CharField(initial="Campaign Reference", widget=forms.HiddenInput)
        I_icon =  forms.CharField(initial=get_StixIcon('Campaign', 'stix.mitre.org'), widget=forms.HiddenInput)
        object_id =  forms.CharField(initial='', widget=forms.HiddenInput)
        label =  forms.CharField(initial='', widget=forms.HiddenInput)

    class StixIndicator(forms.Form):
        CONFIDENCE_TYPES = (
            ('High', 'High'),
            ('Medium', 'Medium'),
            ('Low', 'Low'),
            ('None', 'None'),
            ('Unknown', 'Unknown')
        )

        OPERATOR_TYPES = (
            ('OR', 'OR'),
            ('AND', 'AND'),
        )
        KILL_CHAIN_TYPES = (
            ("", "None"),
            ("stix:KillChainPhase-af1016d6-a744-4ed7-ac91-00fe2272185a", "Reconnaissance"),
            ("stix:KillChainPhase-445b4827-3cca-42bd-8421-f2e947133c16", "Weaponization"),
            ("stix:KillChainPhase-79a0e041-9d5f-49bb-ada4-8322622b162d", "Delivery"),
            ("stix:KillChainPhase-f706e4e7-53d8-44ef-967f-81535c9db7d0", "Exploitation"),
            ("stix:KillChainPhase-e1e4e3f7-be3b-4b39-b80a-a593cfd99a4f", "Installation"),
            ("stix:KillChainPhase-d6dc32b9-2538-4951-8733-3cb9ef1daae2", "Command and Control"),
            ("stix:KillChainPhase-786ca8f9-2d9a-4213-b38e-399af4a2e5d6", "Actions on Objectives")
        )
        object_type = forms.CharField(initial="Indicator", widget=forms.HiddenInput)
        I_object_display_name = forms.CharField(initial="Indicator", widget=forms.HiddenInput)
        I_icon =  forms.CharField(initial=get_StixIcon('Indicator', 'stix.mitre.org'), widget=forms.HiddenInput)
        indicator_title = forms.CharField(max_length=1024)
        indicator_description = forms.CharField(widget=forms.Textarea, required=False)
        indicator_confidence = forms.ChoiceField(choices=CONFIDENCE_TYPES, required=False, initial="med")
        indicator_operator = forms.ChoiceField(choices=OPERATOR_TYPES, required=False, initial="OR",
                                               help_text="Chose 'OR' if any of the observables in the indicator by themselves are indicative of an attack; "
                                                         "chose 'AND' if the observables in this indicator must be present 'together'.")
        kill_chain_phase = forms.ChoiceField(choices=KILL_CHAIN_TYPES, required=False, initial="Unknown")

    class TestMechanismIOC(forms.Form):
        object_type = forms.CharField(initial="Test_Mechanism", widget=forms.HiddenInput)
        object_subtype = forms.CharField(initial="IOC", widget=forms.HiddenInput)
        I_icon =  forms.CharField(initial=static(''), widget=forms.HiddenInput)
        ioc_xml = forms.CharField(initial="", widget=forms.HiddenInput)
        ioc_title = forms.CharField(max_length=1024)
        ioc_description = forms.CharField(widget=forms.Textarea, required=False)

    class TestMechanismYara(forms.Form):
        object_type = forms.CharField(initial="Test_Mechanism", widget=forms.HiddenInput)
        object_subtype = forms.CharField(initial="YARA", widget=forms.HiddenInput)
        I_icon =  forms.CharField(initial=static(''), widget=forms.HiddenInput)
        yara_rules = forms.CharField(initial="", widget=forms.HiddenInput)
        yara_title = forms.CharField(max_length=1024)
        yara_description = forms.CharField(widget=forms.Textarea, required=False)

    class TestMechanismSnort(forms.Form):
        object_type = forms.CharField(initial="Test_Mechanism", widget=forms.HiddenInput)
        object_subtype = forms.CharField(initial="SNORT", widget=forms.HiddenInput)
        I_icon =  forms.CharField(initial=static(''), widget=forms.HiddenInput)
        snort_rules = forms.CharField(initial="", widget=forms.HiddenInput)
        snort_title = forms.CharField(max_length=1024)
        snort_description = forms.CharField(widget=forms.Textarea, required=False)



    """
    Edit view for STIX object describing indicators for a given campaign.
    """
    def get_context_data(self, **kwargs):
        context = super(FormView, self).get_context_data(**kwargs)

        indicatorForms = [self.StixIndicator]
        campaignForms = [self.StixCampaign, self.StixCampaignReference]
        threatActorForms = [self.StixThreatActor, self.StixThreatActorReference]
        testMechanismForms = [self.TestMechanismIOC, self.TestMechanismSnort]

        context['indicatorForms'] = indicatorForms
        context['campaignForms'] = campaignForms
        context['threatActorForms'] = threatActorForms
        context['testMechanismForms'] = testMechanismForms

        return context




class stixTransformer:
    """
    Implements the transformer used to transform the JSON produced by
    the MANTIS Authoring GUI into a valid STIX document.
    """

    def gen_slugged_id(self,id_string):
        ret = ''

        if not id_string:
            ret = id_string
        elif '{' in id_string:
            ns_uri,uid = tuple(id_string[1:].split('}',1))
            if ns_uri in self.namespace_map:
                ret = "%s:%s" % (self.namespace_map[ns_uri],uid)
            else:
                try:
                    ns_slug = IdentifierNameSpace.objects.get(uri=ns_uri).name
                except ObjectDoesNotExist:
                    ns_slug = "authoring"
                if not ns_slug:
                    ns_slug = "authoring"

                if ns_slug in self.namespace_map.values():
                    counter = 0
                    while "%s%d" % (ns_slug,counter) in self.namespace_map.values():
                        counter +=1
                    ns_slug = "%s%d" % (ns_slug,counter)
                self.namespace_map[ns_uri] = ns_slug
                ret = "%s:%s" % (ns_slug,uid)
        else:
            ret = id_string

        if ret:
            return ret.decode('utf-8').encode('ascii')
        return id_string


    def __init__(self, *args,**kwargs):
        # Setup our namespace

        self.namespace_name = kwargs.get('namespace_uri', DINGOS_DEFAULT_ID_NAMESPACE_URI).decode('utf-8').encode('ascii')
        self.namespace_prefix = kwargs.get('namespace_slug', "dingos_default").decode('utf-8').encode('ascii')
        self.namespace_map = {self.namespace_name: self.namespace_prefix,
                              'http://data-marking.mitre.org/Marking-1': 'stixMarking',
                              }




        self.namespace = cybox.utils.Namespace(self.namespace_name, self.namespace_prefix)
        cybox.utils.set_id_namespace(self.namespace)
        stix.utils.set_id_namespace({self.namespace_name: self.namespace_prefix})



        # See if we have a passed JSON
        jsn = kwargs['jsn']
        if type(jsn) == dict:
            self.jsn = copy.deepcopy(jsn)
        else:
            try:
                self.jsn = json.loads(jsn)
            except:
                print 'Error parsing provided JSON'
                return None
        if not self.jsn:
            return None

        # Because the cybox/stix description-type elements
        # are so versatile (they can contain also html),
        # no automated escaping is carried out for these fields.
        # We therefore do the escaping of description-fields here:

        dict_map(escape_descriptions,self.jsn)

        #for section_key in self.jsn:
        #    section = self.jsn[section_key]
        #    if isinstance(section,dict):
        #        for key in section:
        #            if 'description' in key:
        #                section[key] = conditional_escape(section[key])
        #    elif isinstance(section,list):
        #        for item in section:
        #            if isinstance(item,dict):
        #                for key in item:
        #                    if 'description' in key:
        #                        item[key] = conditional_escape(item[key])

        # Some defaults
        self.stix_header = {}
        self.stix_indicators = []
        self.test_mechanisms = []
        self.campaign = None
        self.threatactor = None
        self.indicators = {}
        self.observables = {}
        self.bulk_observable_mapping = {}
        self.cybox_observable_list = None
        self.cybox_observable_references = []

        # Now process the parts
        self.__process_observables()
        self.__process_test_mechanisms()

        self.__process_campaigns()
        self.__process_indicators()
        self.__create_stix_package()

    def __process_campaigns(self):
        """
        Processes the campaigns JSON part
        """
        try:
            campaign = self.jsn['campaign']
        except:
            print "Error. No threat campaigns passed."
            return

        try:
            threatactor = campaign['threatactor']
        except:
            print "Error. No threat actor passed."
            return

        # The campaign
        if campaign.get('object_type') == 'CampaignReference':
            camp = Campaign()
            camp.idref = self.gen_slugged_id(campaign.get('object_id', ''))
            # must remove the timestamp, since the reference is meant
            # to refer to always the latest revision
            camp.timestamp = None
            camp.id_ = None
            self.campaign = camp
        elif campaign.get('name','').strip() != '':
            camp = Campaign()
            campaign_identifier = self.jsn['stix_header']['stix_package_id'].replace('package-','campaign-')
            if campaign_identifier == self.jsn['stix_header']['stix_package_id']:
                # replace did not work
                raise StandardError("Could not derive identifier for campaign from identifier from package")

            camp.id_ = self.gen_slugged_id(campaign_identifier)

            camp.names =  Names(Name(campaign.get('name', '')))
            camp.title = campaign.get('title','')
            camp.description = campaign.get('description', '')
            #camp.confidence = Confidence(campaign.get('confidence', ''))
            camp.status = StixVocabString(campaign.get('status', ''))
            #afrom = Activity()
            #afrom.date_time = DateTimeWithPrecision(value=campaign.get('activity_timestamp_from', ''), precision="minute")
            #afrom.description = StixStructuredText('Timestamp from')
            #ato = Activity()
            #ato.date_time = DateTimeWithPrecision(value=campaign.get('activity_timestamp_to', ''), precision="minute")
            #ato.description = StixStructuredText('Timestamp to')
            #camp.activity = [afrom, ato]
            self.campaign = camp


        if threatactor.get('object_type') == 'ThreatActorReference':
            tac = ThreatActor()
            tac.idref = self.gen_slugged_id(threatactor.get('object_id', ''))
            tac.timestamp=None
            tac.id_ = None
            if self.campaign and self.campaign.id_:
                related_ta1 = ThreatActor()

                related_ta1.idref= self.gen_slugged_id(tac.idref)
                related_ta1.timestamp = None

                self.campaign.attribution.append(related_ta1)


            self.threatactor = tac
        elif threatactor.get('identity_name', '').strip() != '':
            tac = ThreatActor()
            tac_identifier = self.jsn['stix_header']['stix_package_id'].replace('package-','threatactor-')
            if tac_identifier == self.jsn['stix_header']['stix_package_id']:
                # replace did not work
                raise StandardError("Could not derive identifier for threat actor from identifier of package")

            tac.id_ = self.gen_slugged_id(tac_identifier)
            tac_id = tac.id_

            identity_id_format_string = tac_id.replace('threatactor','threatactor-id-%d')

            if identity_id_format_string == tac_id:
                # replace did not work
                raise StandardError("Could not derive identifier for identity from identifier of threat actor")

            related_identities = []
            tac.identity = Identity(id_=identity_id_format_string % 0, idref=None, name=threatactor.get('identity_name', ''))
            counter = 1
            for ia in threatactor.get('identity_aliases', '').split('\n'):
                related_identities.append(Identity(id_=identity_id_format_string % counter, idref=None, name=ia.strip('\n').strip('\r').strip()))
                counter += 1
            tac.identity.related_identities = RelatedIdentities(related_identities)
            tac.title = threatactor.get('title', '')
            tac.description = threatactor.get('description', '')
            #tac.information_source = InformationSource()
            #tac.information_source.description = threatactor.get('information_source', '')
            #tac.confidence = Confidence(threatactor.get('confidence', ''))

            if self.campaign and self.campaign.id_:
                related_ta = ThreatActor()
                related_ta.idref= self.gen_slugged_id(tac_id)
                related_ta.timestamp = None
                self.campaign.attribution.append(related_ta)




            self.threatactor = tac

    def __create_test_mechanism_object(self, test):
        """
        Helper function which creates a test mechansim object according to the passed object type.
        'full' specifies if the structure should be filled, otherweise an empty object is returned (used for referencing)
        """

        tm = False

        if test['object_subtype'] == 'IOC':
            tm = OpenIOCTestMechanism(test['test_mechanism_id'])
            try:
                ioc = test['ioc_xml']
                ioc_xml = etree.parse(StringIO(b64decode(ioc)))
                tm.ioc = ioc_xml
            except Exception as e:
                print 'XML of "%s" not valid: %s' % (test['ioc_title'], str(e))

        elif test['object_subtype'] == 'SNORT':
            tm = SnortTestMechanism(test['test_mechanism_id'])
            tm.rules = b64decode(test['snort_rules']).splitlines()

        return tm



    def __process_test_mechanisms(self):
        """
        Processes the test mechanisms from the JSON.
        """
        try:
            tests = self.jsn['test_mechanisms']
        except:
            print "Error. No test mechanisms passed."
            return


        for test in tests:
            tm = self.__create_test_mechanism_object(test)
            if tm:
                self.test_mechanisms.append(tm)



    def __process_observables(self):
        """
        Processes the observables JSON part and produces a list of observables.
        """
        try:
            observable_definitions = self.jsn['observables']
        except:
            print "Error. No observables passed."
            return

        cybox_object_dict = {}
        relations = {}


        # First collect all object relations.
        for properties_obj in observable_definitions:
            relations[self.gen_slugged_id(properties_obj['observable_id'])] = properties_obj['related_observables']

        for properties_obj in observable_definitions:
            object_type = properties_obj['observable_properties']['object_type']
            object_subtype = properties_obj.get('object_subtype', 'Default')

            im = importlib.import_module('mantis_authoring.cybox_object_transformers.' + object_type.lower())
            template_obj = getattr(im,'TEMPLATE_%s' % object_subtype)()

            id_base = properties_obj['observable_id'].split('}')[1].replace('Observable-','')
            namespace_tag = self.namespace_map[properties_obj['observable_id'][1:].split('}')[0]]

            transform_result = template_obj.process_form(properties_obj['observable_properties'],id_base,namespace_tag)
            if transform_result==None:
                self.cybox_observable_references.append(properties_obj['observable_id'])
                continue


            if isinstance(transform_result,dict):
                result_type = transform_result['type']
                main_properties_obj = transform_result['main_obj_properties_instance']
                properties_obj_list = transform_result['obj_properties_instances']
            else:
                result_type = 'single_obj'
                main_properties_obj = transform_result
                properties_obj_list = []

            if result_type == 'bulk' or result_type == 'obj_with_subobjects':
                old_id = self.gen_slugged_id(properties_obj['observable_id'])
                new_ids = []

                for (id_base,no) in properties_obj_list:
                    # Title and description don't have an effect on the
                    # cybox object, but we use it to transport the
                    # information to the observable we are going to create
                    # later

                    no.mantis_title = properties_obj.get('observable_title', '')
                    no.mantis_description = properties_obj.get('observable_description', '')

                    # New ID
                    _tmp_id =  self.gen_slugged_id("%s:Observable-%s" % (namespace_tag,id_base))
                    cybox_object_dict[_tmp_id] = no
                    new_ids.append(_tmp_id)


                # Now find references to the old observable_id and replace with relations to the new ids.
                # Instead of manipulation the ids, we just generate a new array of relations

                if result_type == 'bulk':
                    self.bulk_observable_mapping[old_id] = new_ids
                    new_relations = {}
                    for obs_id, obs_rel in relations.iteritems():
                        obs_id = self.gen_slugged_id(obs_id)
                        if obs_id==old_id: # our old object has relations to other objects
                            for ni in new_ids: # for each new key ...
                                new_relations[ni] = {}
                                for ork, orv in obs_rel.iteritems(): # ... we insert the new relations
                                    ork = self.gen_slugged_id(ork)
                                    if ork==old_id: # skip entries where we reference ourselfs
                                        continue
                                    new_relations[ni][ork] = orv
                        else: # our old object might be referenced by another one
                            new_relations[obs_id] = {} #create old key
                            #try to find relations to our old object...
                            for ork, orv in obs_rel.iteritems():
                                ork = self.gen_slugged_id(ork)
                                if ork==old_id: # Reference to our old key...
                                    for ni in new_ids: #..insert relation to each new key
                                        new_relations[obs_id][ni] = orv
                                else: #just insert. this has nothing to do with our old key
                                    new_relations[obs_id][ork] = orv

                    relations = new_relations

            if result_type == 'single_obj' or result_type == 'obj_with_subobjects':
                # only one object. No need to adjust relations or ids
                # Title and description don't have an effect on the
                # cybox object, but we use it to transport the
                # information to the observable we are going to create
                # later on

                main_properties_obj.mantis_title = properties_obj.get('observable_title', '')
                main_properties_obj.mantis_description = properties_obj.get('observable_description', '')
                cybox_object_dict[self.gen_slugged_id(properties_obj['observable_id'])] = main_properties_obj


        # Actually, what we have called 'obs' ('Observable') above is not
        # really an observable, but an ObjectProperties instance.
        # We now go one step further and turn the ObjectProperties instance
        # into an Object instance. We need to do this, because as Object,
        # it also carries an identifier, and we need to set the
        # identifier according to the identifier of what will become
        # the surrounding observable. Otherwise, we have random auto-generated
        # identifiers, and that is something we cannot have, because then
        # repeated imports will lead to InfoObjects with always new identifiers
        # rather than the overwriting of existing InfoObjects.

        # Note that the processing of relations has to be carried out *after*
        # the identifiers have been set correctly!!!

        for obs_id in cybox_object_dict.keys():
            cybox_object_dict[obs_id] = Object(cybox_object_dict[obs_id])
            cybox_object_dict[obs_id].id_ = self.gen_slugged_id(obs_id.replace("Observable",cybox_object_dict[obs_id].properties.__class__.__name__))


        # Observables and relations are now processed. The only thing
        # left is to include the relation into the actual objects. The
        # cybox objects are packed into Observables. Title and
        # description of observables are read from the cybox object
        # where we put it before

        self.cybox_observable_list = []
        for obs_id, cybox_obj in cybox_object_dict.iteritems():
            # Observable title and description were transported in our cybox object
            title = cybox_obj.properties.mantis_title
            description = cybox_obj.properties.mantis_description

            for rel_id, rel_type in relations.get(obs_id,{}).iteritems():
                related_object = cybox_object_dict[self.gen_slugged_id(rel_id)].properties
                if not related_object: # This might happen if an observable was not generated (because data was missing); TODO!
                    continue
                cybox_obj.add_related(related_object, rel_type, inline=False)

            cybox_obs = Observable(cybox_obj, obs_id)

            if title.strip():
                cybox_obs.title = title
            if description.strip():
                cybox_obs.description = description

            self.cybox_observable_list.append(cybox_obs)

        return self.cybox_observable_list





    def __create_stix_indicator(self, indicator):
        """
        Helper function to create an Indicator object
        """
        stix_indicator = Indicator(self.gen_slugged_id(indicator['indicator_id']))
        stix_indicator.title = indicator['indicator_title']
        stix_indicator.description = indicator['indicator_description']
        stix_indicator.confidence = Confidence(indicator['indicator_confidence'])
        stix_indicator.observable_composition_operator = indicator['indicator_operator']
        #stix_indicator.indicator_types = indicator['object_type']

        if 'kill_chain_phase' in indicator:
            if indicator['kill_chain_phase'].strip() != '' and indicator['kill_chain_phase'] in {x[0]:x[1] for x in FormView.StixIndicator.KILL_CHAIN_TYPES}:
                stix_indicator.add_kill_chain_phase(
                    KillChainPhase(indicator['kill_chain_phase'])
                )


        return stix_indicator



    def __process_indicators(self):
        """
        Processes the indicator JSON part. Sets the stix_indicators
        which be picked up by the create_stix_package. (observables
        referenced in an indicator will be included there while loose
        observables are not inlcluded in any indicator and will just
        be appended to the package by create_stix_package)
        """


        indicators = self.jsn['indicators']
        already_included_tests = [] # used to record already included test_mechanisms so we dont insert doubles but references to the already inserted ones

        self.stix_indicators = []

        for indicator in indicators:
            stix_indicator = self.__create_stix_indicator(indicator)
            related_observables = indicator['related_observables']
            related_test_mechanisms = indicator['related_test_mechanisms']

            # Add the observables to the indicator
            for related_observable_id in related_observables:
                related_observable_id = self.gen_slugged_id(related_observable_id)
                if related_observable_id in self.bulk_observable_mapping:
                    for related_id in self.bulk_observable_mapping[related_observable_id]:
                        obs_rel = Observable()
                        obs_rel.idref = self.gen_slugged_id(related_id)
                        obs_rel.id_ = None

                        stix_indicator.add_observable(obs_rel)
                else:
                    obs_rel = Observable()
                    obs_rel.idref = self.gen_slugged_id(related_observable_id)
                    obs_rel.id_ = None
                    stix_indicator.add_observable(obs_rel)

            # TODO: Not dealing with references, yet!
            # Add observable references to the indicator
            #for obs_ref in self.cybox_observable_references:
            #    obs_rel = Observable()
            #    obs_rel.idref = obs_ref
            #    obs_rel.id_ = None
            #    stix_indicator.add_observable(obs_rel)

            # Add the test mechanisms to the indicator
            for tm in self.test_mechanisms:
                check_tes_id = tm.id_
                if check_tes_id in related_test_mechanisms:
                    # If we already included this test, we only reference it
                    if check_tes_id in already_included_tests:
                        test_mechanism_ref = tm.__class__()
                        test_mechanism_ref.id_ = None
                        test_mechanism_ref.idref = self.gen_slugged_id(check_tes_id)
                        stix_indicator.add_test_mechanism(test_mechanism_ref)
                    else:
                        stix_indicator.add_test_mechanism(tm)
                        already_included_tests.append(check_tes_id)

            # Add reference to campaign
            if self.campaign:

                ref_camp = Campaign()
                ref_camp.id_ = None
                ref_camp.timestamp=None
                if self.campaign.id_:
                    ref_camp.idref = self.gen_slugged_id(self.campaign.id_)
                else:
                    ref_camp.idref = self.gen_slugged_id(self.campaign.idref)
                indicator_assoc_campaigns = AssociatedCampaigns()

                indicator_assoc_campaigns.append(ref_camp)

                # TODO: This below does not work, because the
                # python-stix api does not support the Associated Campaigns for
                # indicators.

                stix_indicator.associated_campaigns = indicator_assoc_campaigns

            self.stix_indicators.append(stix_indicator)


    def __create_stix_package(self):
        """
        Creates the STIX XML. __process_observables and __process_indicators must be called before
        """
        try:
            stix_properties = self.jsn['stix_header']
            observables = self.jsn['observables']
        except:
            print "Error. No header passed."
            return

        stix_indicators = self.stix_indicators

        #stix_id_generator = stix.utils.IDGenerator(namespace={self.namespace_name: self.namespace_prefix})
        #stix_id = stix_id_generator.create_id()
        stix_id = self.gen_slugged_id(stix_properties['stix_package_id'])
        #spec = MarkingSpecificationType(idref=stix_id)
        spec = MarkingSpecification()
        #spec.idref = stix_id
        #spec.set_Controlled_Structure("//node()")
        spec.controlled_structure = "//node()"
        #tlpmark = TLPMarkingStructureType()
        #tlpmark.set_color(stix_properties['stix_header_tlp'])
        tlpmark = TLPMarkingStructure()
        tlpmark.color = stix_properties['stix_header_tlp'].decode('utf-8').encode('ascii').upper()
        spec.marking_structures.append(tlpmark)
        stix_package = STIXPackage(
            indicators=stix_indicators,
            observables=Observables(self.cybox_observable_list),
            id_=stix_id.decode('utf-8').encode('ascii'),
            threat_actors=self.threatactor)
        stix_header = STIXHeader()
        stix_header.title = stix_properties['stix_header_title']
        stix_header.description = stix_properties['stix_header_description']
        stix_header.handling = Marking([spec])
        stix_information_source = InformationSource()
        stix_information_source.time = Time(produced_time=datetime.datetime.now(pytz.timezone('Europe/Berlin')).isoformat())
        stix_information_source.tools = ToolInformationList([ToolInformation(tool_name="Mantis Authoring GUI", tool_vendor="Siemens CERT")])
        stix_header.information_source = stix_information_source
        stix_package.stix_header = stix_header
        if self.campaign:
            stix_package.campaigns.append(self.campaign)

        self.stix_package = stix_package.to_xml(ns_dict=self.namespace_map,
                                                auto_namespace=True)
        return self.stix_package



    def getStix(self):
        try:
            return self.stix_package
        except:
            return None





class ProcessingView(BasicProcessingView):

    author_view = FORM_VIEW_NAME
    transformer = stixTransformer
    importer_class = STIX_Import






class UploadFile(AuthoringMethodMixin,View):
    """
    Handles an uploaded file. Tries to detect the type according to the content and returns the appropriate object (e.g. file-observable)
    """

    def post(self, request, *args, **kwargs):
        res = {
            'status': False,
            'msg': 'An error occured.',
            'data': {}
        }

        cache = caches['default']

        POST = self.request.POST
        post_dict = parser.parse(str(POST.urlencode()))
        ns_info = self.get_authoring_namespaces(self.request.user,fail_silently=False)


        # If our request contains a type and a filekey, the UI wants us to import a specific file with a specific module
        if post_dict.has_key('fid') and post_dict.has_key('type'):

            fid = post_dict.get('fid', '')
            ftype = post_dict.get('type', '')

            # Get file properties from cache
            te = cache.get('MANTIS_AUTHORING__file__' + fid)

            # BUG: sometimes te is None. We still need to figure out why.
            # As for now, we just tell the user to try this indicator again...
            if not te:
                res['msg'] = "We're sorry! An error occured processing the file. Please try again..."
                print 'te', te
                print 'post_dict', post_dict

            if (fid!='' and ftype!='') and (te) and (os.path.isfile(te['cache_file'])):
                # Iterate over available file processors and filter those with the correct type the GUI wants us to use.
                mods_dir = os.path.dirname(os.path.realpath(__file__))
                mods = [x[:-3] for x in os.listdir(os.path.join(mods_dir, 'file_analysis')) if x.endswith(".py") and not x.startswith('__')]
                proc_modules = []
                for mod in mods:
                    im = importlib.import_module('mantis_authoring.file_analysis.' + mod)
                    ao = getattr(im,'file_analyzer')(te)
                    if ao.is_class_type(ftype):
                        proc_modules.append(ao)

                if not proc_modules:
                    res['msg'] = 'Could not find suitable modules for the requested processing type.'
                else:
                    mod = proc_modules[0]
                    proc_res = mod.process(ns_info=ns_info)
                    if not proc_res:
                        pass
                    elif not proc_res['status']:
                        res['msg'] = proc_res['data']
                    else:
                        res['status'] = True
                        res['data'] = proc_res['data']
                        res['action'] = 'create'

        else:
            FILES = request.FILES
            f = False
            if FILES.has_key(u'file'):
                f = FILES['file']
                # GUI passed allowed file types
                req_type = request.POST.get('dda_dropzone_type_allow', None)
                proc_modules = []

                # Iterate over available file processors and filter those with the correct type the GUI wants us to use.
                mods_dir = os.path.dirname(os.path.realpath(__file__))
                mods = [x[:-3] for x in os.listdir(os.path.join(mods_dir, 'file_analysis')) if x.endswith(".py") and not x.startswith('__')]
                for mod in mods:
                    im = importlib.import_module('mantis_authoring.file_analysis.' + mod)
                    ao = getattr(im,'file_analyzer')(f)
                    if ao.is_class_type(req_type):
                        proc_modules.append(ao)

                #TODO: we call test_object() 3 times below. We should only need to call it once.

                if not proc_modules:
                    res['msg'] = 'Could not find suitable modules for the requested processing type.'

                else:
                    # Now iterate over the modules in question and check if they can successfully handle our file
                    mod_choices = []
                    for mod in proc_modules:
                        if mod.test_object() is not False:
                            mod_choices.append(mod)

                    if not mod_choices:
                        res['msg'] = 'Could not find a module that successfully parses file "%s"' % f.name
                    else:
                        # We have at least one module that qualifies for the processing
                        if len(mod_choices) > 1:
                            # There are more than one modules. Let the user choose
                            res['status'] = True
                            res['action'] = 'ask'
                            res['action_url'] = reverse('url.mantis_authoring.upload_file')
                            res['action_msg'] = 'File "%s" qualifies for more than one observable types. Please choose:' % f.name
                            res['data'] = []
                            file_id = str(uuid4())
                            for mod in mod_choices:
                                res['data'].append({
                                    'fid': file_id,
                                    'type': mod.test_object(),
                                    'title': mod.test_object(),
                                    'details': mod.get_description()
                                })
                            # Cache file for later use on disk. Cache file descriptor in django cache (local cache if nothing else is configured)
                            dest_path = settings.MANTIS_AUTHORING.get('FILE_CACHE_PATH')
                            if not os.path.isdir(dest_path):
                                os.mkdir(dest_path)
                            dest_file = tempfile.NamedTemporaryFile(dir=dest_path, delete=False)
                            for chunk in f:
                                dest_file.write(chunk)
                            dest_file.close()

                            # Cache file meta
                            cache.set('MANTIS_AUTHORING__file__' + file_id, { 'cache_file': dest_file.name, 'filename': f.name }, 10 * 60)


                        else:
                            # There is only one module. Use that and process the file
                            mod = mod_choices[0]
                            proc_res = mod.process(ns_info=ns_info)
                            if not proc_res:
                                pass
                            elif not proc_res['status']:
                                res['msg'] = proc_res['data']
                            else:
                                res['status'] = True
                                res['data'] = proc_res['data']
                                res['action'] = 'create'


        if not request.is_ajax(): # Indicates fallback (form based upload)
            ret  = '<script>'
            ret += '  var r = ' + json.dumps(res) + ';';
            ret += '  window.top._handle_file_upload_response(r);'
            ret += '</script>'
            return HttpResponse(ret)
        else: # Fancy upload with drag and drop can handle json response
            return HttpResponse(json.dumps(res), content_type="application/json")
