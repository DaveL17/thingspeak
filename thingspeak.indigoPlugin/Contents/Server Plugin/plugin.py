#!/usr/bin/env python2.6
# -*- coding: utf-8 -*-

"""
:filename: plugin.py
:author: DaveL17

Thingspeak Plugin

The Thingspeak Plugin for Indigo Home Control provides a facility to manage
Thingspeak channels and upload data. The plugin takes device and variable
values and uploads them to Thingspeak. In order to use it, you will need to
have a Thingspeak account, and have configured Thingspeak channels. The plugin
uses the master Thingspeak API key to access and manage each channel. To use
the plugin, create individual Indigo devices that represent a single
Thingspeak channel. Under the device configuration menu, assign Indigo devices
or  variables to each "Thing." Each plugin device can hold up to eight
variables (a Thingspeak limit.) Currently, only numeric and binary  variables
will chart on Thingspeak, and the plugin tries to adjust variable values as
needed to make them compatible (i.e., converting a string to a float).

Credits
 - Karl (kw123) - device state restriction methods

Thingspeak API - https://www.mathworks.com/help/thingspeak/
"""

# =================================== TO DO ===================================

# TODO: Combine dynamic list method calls using filter (like Matplotlib).

# ================================== IMPORTS ==================================

# Built-in modules
from dateutil.parser import parse as du_parse
import datetime as dt
import logging
import os
import pytz
import requests
import time as t
import traceback

# Third-party modules
try:
    import indigo
except ImportError:
    pass
try:
    import pydevd
except ImportError:
    pass

# My modules
import DLFramework.DLFramework as Dave

# =================================== HEADER ==================================

__author__    = Dave.__author__
__copyright__ = Dave.__copyright__
__license__   = Dave.__license__
__build__     = Dave.__build__
__title__     = 'Thingspeak Plugin for Indigo Home Control'
__version__   = '1.2.12'

# =============================================================================

install_path = indigo.server.getInstallFolderPath()

kDefaultPluginPrefs = {
    u'apiKey':                    "",     # Thingspeak API key.
    u'configMenuTimeoutInterval': 15,     # How long to wait on a server timeout.
    u'deviceIP':                  "XXX.XXX.XXX.XXX:3000",  # Local Thingspeak server IP.
    u'devicePort':                False,  # Use local Thingspeak server.
    u'elevation':                 0,      # Elevation of data source.
    u'latitude':                  0,      # Latitude of data source.
    u'longitude':                 0,      # Longitude of data source.
    u'showDebugInfo':             False,  # Verbose debug logging?
    u'showDebugLevel':            1,      # Low, Medium or High debug output.
    u'twitter':                   "",     # Username linked to ThingTweet
    }


class Plugin(indigo.PluginBase):
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.pluginIsInitializing = True
        self.pluginIsShuttingDown = False

        # ============================ Configure Logging ==============================
        # Convert from legacy ['low', 'medium', 'high'] or [1, 2, 3].
        try:
            if int(self.pluginPrefs.get('showDebugLevel', '30')) < 10:
                self.pluginPrefs['showDebugLevel'] *= 10
        except ValueError:
            self.pluginPrefs['showDebugLevel'] = 30

        self.debugLevel = self.pluginPrefs['showDebugLevel']
        log_format = '%(asctime)s.%(msecs)03d\t%(levelname)-10s\t%(name)s.%(funcName)-28s %(msg)s'
        self.plugin_file_handler.setFormatter(logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S'))
        self.indigo_log_handler.setLevel(self.debugLevel)

        self.uploadNow      = False  # Call to upload from menu, action in process
        self.updating       = False  # Plugin in process of updating channels

        # =========================== Initialize DLFramework ===========================

        self.Fogbert = Dave.Fogbert(self)
        self.devicesAndVariablesList = self.Fogbert.deviceAndVariableList()

        # Log pluginEnvironment information when plugin is first started
        self.Fogbert.pluginEnvironment()

        # try:
        #     pydevd.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True, suspend=False)
        # except:
        #     pass

        # ============================ Deprecation Notice =============================
        # We want to make sure these messages will be printed to the log regardless of
        # the current debug level settings.
        self.indigo_log_handler.setLevel(30)
        self.logger.warning(u"Due to changes in Thingspeak's pricing model, the Thingspeak Plugin has been deprecated.")
        self.logger.warning(u"You are strongly encouraged to find an alternative solution.")
        self.indigo_log_handler.setLevel(self.debugLevel)
        t.sleep(3)

        self.pluginIsInitializing = False

    def __del__(self):

        indigo.PluginBase.__del__(self)

    # =============================================================================
    # ============================== Indigo Methods ===============================
    # =============================================================================
    def closedPrefsConfigUi(self, values_dict, user_cancelled):

        if not user_cancelled:

            self.logger.debug(unicode(values_dict))
            self.logger.warning(u"Warning! Debug output contains sensitive information.")

            # Ensure that self.pluginPrefs includes any recent changes.
            for k in values_dict:
                self.pluginPrefs[k] = values_dict[k]

            self.logger.debug(u"User prefs saved.")

        else:
            self.logger.debug(u"User prefs dialog cancelled.")

        # Update update select globals if plugin prefs have changed.
        self.debugLevel = int(self.pluginPrefs.get('showDebugLevel', '30'))
        self.indigo_log_handler.setLevel(self.debugLevel)

    # =============================================================================
    def deviceStartComm(self, dev):

        self.logger.debug(u"Starting device: {0}".format(dev.name))
        dev.stateListOrDisplayStateIdChanged()
        dev.updateStateOnServer('thingState', value=False, uiValue=u"waiting")
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    # =============================================================================
    def deviceStopComm(self, dev):

        self.logger.debug(u"Stopping device: {0}".format(dev.name))
        dev.updateStateOnServer('thingState', value=False, uiValue=u"disabled")
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    # =============================================================================
    def getDeviceConfigUiValues(self, values_dict, type_id, dev_id):

        # Get latest list of Indigo devices and variables. We don't return
        # it from here, but we want it updated any time a device config is
        # opened.
        self.devicesAndVariablesList = self.Fogbert.deviceAndVariableList()

        return values_dict

    # =============================================================================
    def runConcurrentThread(self):

        self.logger.debug(u"runConcurrentThread() initiated.")

        try:
            while True:
                if not self.updating and not self.uploadNow:
                    self.updating = True
                    self.encodeValueDicts()

                # We check every 2 seconds to see if any devices need updating.
                self.sleep(2)

        except self.StopThread:
            self.logger.debug(u"Thingspeak stop thread called.")
            pass

    # =============================================================================
    def sendDevicePing(self, dev_id=0, suppress_logging=False):

        indigo.server.log(u"Thingspeak Plugin devices do not support the ping function.")
        return {'result': 'Failure'}

    # =============================================================================
    def startup(self):

        # =========================== Audit Indigo Version ============================
        self.Fogbert.audit_server_version(min_ver=7)

        self.logger.warning(u"Warning! Debug output may contain sensitive information.")

    # =============================================================================
    def shutdown(self):

        self.pluginIsShuttingDown = True

        for dev in indigo.devices.iter('self'):
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    # =============================================================================
    def validatePrefsConfigUi(self, values_dict):

        error_msg_dict = indigo.Dict()

        # ================================= API Key ===================================
        # Key must be 16 characters in length
        if len(values_dict['apiKey']) not in (0, 16):
            error_msg_dict['apiKey'] = u"The API Key must be 16 characters long."

        # Test key against ThingSpeak service
        if not values_dict['devicePort']:
            try:
                ts_ip = "https://api.thingspeak.com/channels.json?api_key={0}".format(values_dict['apiKey'])
                response = requests.get(ts_ip, timeout=1.50)

                if response.status_code == 401:
                    raise ValueError

            except requests.exceptions.Timeout:
                self.Fogbert.pluginErrorHandler(traceback.format_exc())
                self.logger.warning(u"Unable to confirm accuracy of API Key with the ThingSpeak service.")

            except ValueError:
                self.Fogbert.pluginErrorHandler(traceback.format_exc())
                error_msg_dict['apiKey'] = u"ThingSpeak rejected your API Key as invalid. Please ensure that your " \
                                           u"key is entered correctly."

        # ============================ Latitude / Longitude ===========================
        # Must be integers or floats. Can be negative.
        try:
            float(values_dict['latitude'])
        except ValueError:
            values_dict['latitude'] = 0.0
            error_msg_dict['latitude'] = u"Please enter a number (positive, negative or zero)."

        try:
            float(values_dict['longitude'])
        except ValueError:
            values_dict['longitude'] = 0.0
            error_msg_dict['longitude'] = u"Please enter a number (positive, negative or zero)."

        # ================================= Elevation =================================
        # Must be an integer (can not be a float. Can be negative.
        try:
            int(values_dict['elevation'])
        except ValueError:
            values_dict['elevation'] = 0
            error_msg_dict['elevation'] = u"Please enter a whole number integer (positive, negative or zero)."

        if "." in str(values_dict['elevation']):
            values_dict['elevation'] = 0
            error_msg_dict['elevation'] = u"Please enter a whole number integer (positive, negative or zero)."

        if len(error_msg_dict) > 0:
            error_msg_dict['showAlertText'] = u"Configuration Errors\n\nThere are one or more settings that need to " \
                                              u"be corrected. Fields requiring attention will be highlighted."
            return values_dict, error_msg_dict

        return True, values_dict

    # =============================================================================
    # ============================== Plugin Methods ===============================
    # =============================================================================
    def channelListGenerator(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Generate a list of channel names and IDs

        The channelListGenerator() method generates a list of channel names
        and IDs which are used to identify the target channel.

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        :return: [(channel_id, channel_name), (channel_id, channel_name)]
        """

        url   = "/channels.json"
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('get', url, parms)

        return [(item['id'], item['name']) for item in response_dict]

    # =============================================================================
    def channelClearFeed(self, values_dict, type_id):
        """
        Clear Thingspeak channel using Thingspeak API

        The channelClearFeed() method is called when a user selects 'Clear
        Channel Data' from the plugin menu. It is used to clear all data from
        the channel (the channel remains intact.

        -----

        :param values_dict:
        :param type_id:
        """

        url = "/channels/{0}/feeds.xml".format(values_dict['channelList'])
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('delete', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully cleared.".format(response))
        else:
            self.logger.warning(u"Problem clearing channel data.")

        return True

    # =============================================================================
    def channelDelete(self, values_dict, type_id):
        """
        Delete Thingspeak channel using Thingspeak API

        The channelDelete() method is called when a user selects 'Delete
        a Channel' from the plugin menu. It is used to delete a channel from
        Thingspeak.

        -----

        :param values_dict:
        :param type_id:
        :return bool:
        """

        url = "/channels/{0}.xml".format(values_dict['channelList'])
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('delete', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully deleted.".format(response))
        else:
            self.logger.warning(u"Problem deleting channel data.")

        return True

    # =============================================================================
    def getParms(self, values_dict):
        """
        Construct the API URL for upload to Thingspeak

        Construct the values needed for the data upload to the Thingspeak server.

        -----

        :param values_dict:
        """

        # Thingspeak requires a string representation of the boolean value.
        if values_dict['public_flag']:
            public_flag = 'true'
        else:
            public_flag = 'false'

        parms = {'api_key':     self.pluginPrefs.get('apiKey', ''),  # User's API key. This is different from a channel API key, and can be found in account profile page. (required).
                 'elevation':   self.pluginPrefs.get('elevation', 0),  # Elevation in meters (optional)
                 'latitude':    self.pluginPrefs.get('latitude', 0),  # Latitude in degrees (optional)
                 'longitude':   self.pluginPrefs.get('longitude', 0),  # Longitude in degrees (optional)
                 'description': values_dict['description'],  # Description of the channel (optional)
                 'field1':      values_dict['field1'],  # Field 1 name (optional)
                 'field2':      values_dict['field2'],  # Field 2 name (optional)
                 'field3':      values_dict['field3'],  # Field 3 name (optional)
                 'field4':      values_dict['field4'],  # Field 4 name (optional)
                 'field5':      values_dict['field5'],  # Field 5 name (optional)
                 'field6':      values_dict['field6'],  # Field 6 name (optional)
                 'field7':      values_dict['field7'],  # Field 7 name (optional)
                 'field8':      values_dict['field8'],  # Field 8 name (optional)
                 'metadata':    values_dict['metadata'],  # Metadata for the channel, which can include JSON, XML, or any other data (optional)
                 'name':        values_dict['name'],  # Name of the channel (optional)
                 'public_flag': public_flag,  # Whether the channel is public, default 'false' (optional, string required if present)
                 'tags':        values_dict['tags'],  # Comma-separated list of tags (optional)
                 'url':         values_dict['url'],  # Web page URL for the channel (optional)
                 }

        return parms

    # =============================================================================
    def channelCreate(self, values_dict, type_id):
        """
        Create Thingspeak channel using Thingspeak API

        The channelCreate() method is called when a user selects 'Create a
        Channel' from the plugin menu. It is used to create a new channel on
        Thingspeak.

        -----

        :param values_dict:
        :param type_id:
        """

        url = "/channels.json"

        parms = self.getParms(values_dict)

        response, response_dict = self.sendToThingspeak('post', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully created.".format(response))
            return True
        else:
            self.logger.warning(u"Problem creating channel.")
            return False

    # =============================================================================
    def channelList(self):
        """
        List current Thingspeak channels

        The channelList() method is called when a user selects 'List
        Channels' from the plugin menu. It is used to print a table of select
        channel information to the Indigo Events log.

        -----

        """

        url = "/channels.json"
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('get', url, parms)

        if response == 200:
            write_key = ""
            indigo.server.log(u"{0:<8}{1:<25}{2:^9}{3:<21}{4:^10}{5:<18}".format('ID',
                                                                                 'Name',
                                                                                 'Public',
                                                                                 'Created At',
                                                                                 'Ranking',
                                                                                 'Write Key'
                                                                                 )
                              )
            indigo.server.log(u"{0:{1}^100}".format("", "="))
            for thing in response_dict:
                for key in thing['api_keys']:
                    if key['write_flag']:
                        write_key = key['api_key']
                indigo.server.log(u"{0:<8}{1:<25}{2:^9}{3:<21}{4:^10}{5:<18}".format(thing['id'],
                                                                                     thing['name'],
                                                                                     thing['public_flag'],
                                                                                     thing['created_at'],
                                                                                     thing['ranking'],
                                                                                     write_key
                                                                                     )
                                  )

            return True

        else:
            return False

    # =============================================================================
    def channelUpdate(self, values_dict, type_id):
        """
        Update Thingspeak channel using Thingspeak API

        The channelUpdate() method is called when a user selects 'Update
        a Channel' from the plugin menu. It is used to make changes to channel
        settings.

        -----

        :param values_dict:
        :param type_id:
        """

        url = "/channels/{0}.json".format(values_dict['channelList'])

        # Validation
        if not values_dict['channelList']:
            error_msg_dict = indigo.Dict()
            error_msg_dict['channelList'] = u"Please select a channel to update."
            error_msg_dict['showAlertText'] = u"Update Channel Info Error:\n\nYou must select a channel to update."
            return False, values_dict, error_msg_dict

        parms = self.getParms(values_dict)

        # Get rid of empty key/value pairs so we don't overwrite existing information.
        for key in parms.keys():
            if parms[key] == "":
                del parms[key]

        response, response_dict = self.sendToThingspeak('put', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully updated.".format(response))
            return True
        else:
            self.logger.warning(u"Problem updating channel settings.")
            return False, values_dict

    # =============================================================================
    def commsKillAll(self):
        """
        Disable communication for all plugin devices

        commsKillAll() sets the enabled status of all plugin devices to
        false.

        -----

        """

        for dev in indigo.devices.itervalues("self"):
            indigo.device.enable(dev, value=False)

    # =============================================================================
    def commsUnkillAll(self):
        """
        Enable communication for all plugin devices

        commsUnkillAll() sets the enabled status of all plugin devices
        to true.

        -----

        """

        for dev in indigo.devices.itervalues("self"):
            indigo.device.enable(dev, value=True)

    # =============================================================================
    def devPrepareForThingspeak(self, dev, parms):
        """
        Upload data to Thingspeak and evaluate the result

        This method performs the upload to Thingspeak, evaluates, and logs the
        result.

        -----

        :param dev:
        :param parms:
        """

        url = "/update.json"

        response, response_dict = self.sendToThingspeak('post', url, parms)

        # Process the results. Thingspeak will respond with a "0" if something went
        # wrong.
        if response == 0:
            self.logger.warning(u"Something went wrong.")
            self.logger.warning(u"{0}".format(response_dict))

            return False

        if response == 200:

            dev.updateStateOnServer('channel_id', value=int(response_dict.get('channel_id', "0")))
            dev.updateStateOnServer('elevation', value=int(response_dict.get('elevation', "0")))
            dev.updateStateOnServer('entry_id', value=int(response_dict.get('entry_id', "0")))
            dev.updateStateOnServer('latitude', value=float(response_dict.get('latitude', "0")))
            dev.updateStateOnServer('longitude', value=float(response_dict.get('longitude', "0")))
            dev.updateStateOnServer('status', value=response_dict.get('status', "0"))

            # For thing values 1-8
            for _ in range(1, 9):
                dev.updateStateOnServer('thing{0}'.format(_), value=response_dict.get('field{0}'.format(_), "0"))

            # Convert UTC return to local time. There is an optional timezone parameter
            # that can be used in the form of: time_zone="timezone=America%2FChicago&"
            # For now, we will convert to UTC locally.
            if response_dict['created_at']:
                time = t.time()

                # time_delta_to_utc formula thanks to Karl (kw123).
                time_delta_to_utc = (int(t.mktime(dt.datetime.utcfromtimestamp(time + 10).timetuple()) - time) / 100) * 100
                utc_obj = du_parse(response_dict['created_at'])

                local_time = str(utc_obj - dt.timedelta(seconds=time_delta_to_utc))
                dev.updateStateOnServer('created_at', value=local_time)
            else:
                dev.updateStateOnServer('created_at', value=u"Unknown")

            new_props = dev.pluginProps
            new_props['address'] = dev.states['channel_id']
            dev.replacePluginPropsOnServer(new_props)

            dev.updateStateOnServer('thingState', value=True, uiValue=u"OK")
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
            return True

    # TODO: Combine these eight generators into one using the filter attribute.
    #       See Matplotlib Stock Bar Chart as an example.
    # =============================================================================
    def devStateGenerator1(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        The following eight methods produce lists of states that are associated
        with user-selected devices when configuring Thingspeak reporting
        devices. Each list includes only states for the selected device.

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        """

        if not values_dict:
            return []

        if values_dict and "thing1" in values_dict:
            if values_dict['thing1'] != "":
                try:
                    if int(values_dict['thing1']) in indigo.devices:
                        dev = indigo.devices[int(values_dict['thing1'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(values_dict['thing1']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    # =============================================================================
    def devStateGenerator2(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        """

        if not values_dict:
            return []

        if values_dict and "thing2" in values_dict:

            # If an item has been selected.
            if values_dict['thing2'] != "":
                try:
                    if int(values_dict['thing2']) in indigo.devices:
                        dev = indigo.devices[int(values_dict['thing2'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(values_dict['thing2']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    # =============================================================================
    def devStateGenerator3(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        """

        if not values_dict:
            return []

        if values_dict and "thing3" in values_dict:
            if values_dict['thing3'] != "":
                try:
                    if int(values_dict['thing3']) in indigo.devices:
                        dev = indigo.devices[int(values_dict['thing3'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(values_dict['thing3']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    # =============================================================================
    def devStateGenerator4(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        """

        if not values_dict:
            return []

        if values_dict and "thing4" in values_dict:
            if values_dict['thing4'] != "":
                try:
                    if int(values_dict['thing4']) in indigo.devices:
                        dev = indigo.devices[int(values_dict['thing4'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(values_dict['thing4']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    # =============================================================================
    def devStateGenerator5(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        """

        if not values_dict:
            return []

        if values_dict and "thing5" in values_dict:
            if values_dict['thing5'] != "":
                try:
                    if int(values_dict['thing5']) in indigo.devices:
                        dev = indigo.devices[int(values_dict['thing5'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(values_dict['thing5']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    # =============================================================================
    def devStateGenerator6(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        """

        if not values_dict:
            return []

        if values_dict and "thing6" in values_dict:
            if values_dict['thing6'] != "":
                try:
                    if int(values_dict['thing6']) in indigo.devices:
                        dev = indigo.devices[int(values_dict['thing6'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(values_dict['thing6']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    # =============================================================================
    def devStateGenerator7(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        """

        if not values_dict:
            return []

        if values_dict and "thing7" in values_dict:
            if values_dict['thing7'] != "":
                try:
                    if int(values_dict['thing7']) in indigo.devices:
                        dev = indigo.devices[int(values_dict['thing7'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(values_dict['thing7']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    # =============================================================================
    def devStateGenerator8(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        """

        if not values_dict:
            return []

        if values_dict and "thing8" in values_dict:
            if values_dict['thing8'] != "":
                try:
                    if int(values_dict['thing8']) in indigo.devices:
                        dev = indigo.devices[int(values_dict['thing8'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(values_dict['thing8']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    # =============================================================================
    def encodeValueDicts(self):
        """
        Encode the data dicts for upload to Thingspeak

        The encodeValueDicts() method is called when a device makes a call
        to upload data to Thingspeak.

        -----

        """

        api_key = None
        thing_dict = {}

        for dev in indigo.devices.itervalues("self"):

            # A device has been created, but hasn't been saved yet.
            if not dev.configured:
                indigo.server.log(u"A device is being (or has been) created, but it's not fully configured. "
                                  u"Sleeping while you finish.")
                continue

            elif not dev.enabled:
                continue

            # Iterate over up to 8 values per device.
            elif dev.enabled:

                # For each device, see if it is time for an update
                last_update = dev.states.get('created_at', '1970-01-01 00:00:00+00:00')
                if last_update == '':
                    last_update = '1970-01-01 00:00:00'
                last_update = du_parse(last_update)

                delta = dt.datetime.now().replace(tzinfo=pytz.utc) - last_update.replace(tzinfo=pytz.utc)
                delta = int(delta.total_seconds())

                if self.uploadNow or delta > int(dev.pluginProps['devUploadInterval']):
                    dev.updateStateOnServer('thingState', value=False, uiValue="processing")

                    channel_id     = dev.pluginProps['channelList']
                    url            = "/channels.json"
                    parms          = {'api_key': self.pluginPrefs.get('apiKey', '')}

                    response, response_dict = self.sendToThingspeak('get', url, parms)

                    # Find the write api key for this channel (we go and get it in case it's changed.
                    for thing in response_dict:
                        if str(thing['id']) == str(channel_id):
                            for key in thing['api_keys']:
                                if key['write_flag']:
                                    api_key = key['api_key']

                    if not api_key:
                        return

                    for v in range(1, 9):
                        thing_str       = 'thing{0}'.format(v)
                        thing_state_str = 'thing{0}State'.format(v)

                        # Create the dict and add the API key to it.
                        thing_dict['key'] = api_key

                        # If there is a device created, but no value assigned.
                        if not dev.pluginProps[thing_str] or dev.pluginProps[thing_str] == "None":
                            var = "Null value"

                        else:
                            thing_1 = dev.pluginProps[thing_str]
                            state_1 = dev.pluginProps[thing_state_str]

                            self.logger.debug(u"{0:{1}^22}".format('', ' '))
                            self.logger.debug(u"ID: {0}".format(thing_1))
                            self.logger.debug(u"Item: {0}".format(state_1))

                            # If it's a device state, do this:
                            if int(thing_1) in indigo.devices:

                                try:
                                    var = indigo.devices[int(thing_1)].states[state_1]
                                    var = self.onlyNumerics(var)
                                    self.logger.debug(u"Value: {0}".format(var))

                                except ValueError:
                                    self.Fogbert.pluginErrorHandler(traceback.format_exc())
                                    self.logger.warning(u"{0} - {1} is non-numeric or has been removed. "
                                                        u"Will try to upload, but it won't "
                                                        u"chart.".format(dev.name, dev.pluginProps[thing_str]))
                                    var = u"undefined"

                                # Add device state value to dictionary.
                                thing_dict['field' + str(v)] = var

                            # If it's a variable value, do this:
                            elif int(thing_1) in indigo.variables:
                                var = indigo.variables[int(thing_1)].value

                                try:
                                    var = self.onlyNumerics(var)
                                    self.logger.debug(u"Value: {0}".format(var))

                                except ValueError:
                                    self.Fogbert.pluginErrorHandler(traceback.format_exc())
                                    self.logger.warning(u"{0} - {1} is non-numeric or has been removed. "
                                                        u"Will try to upload, but it won't "
                                                        u"chart.".format(dev.name, dev.pluginProps[thing_str]))

                                # Add variable value to dictionary.
                                thing_dict['field' + str(v)] = var

                        thing_dict['elevation']  = self.pluginPrefs['elevation']
                        thing_dict['latitude']   = self.pluginPrefs['latitude']
                        thing_dict['longitude']  = self.pluginPrefs['longitude']
                        thing_dict['twitter']    = self.pluginPrefs['twitter']
                        thing_dict['tweet']      = u"{0}".format(dev.pluginProps['tweet'])

                    self.logger.debug(unicode(thing_dict))

                    # Open a connection and upload data to Thingspeak
                    try:

                        # The plugin uploads variable values before moving on to the next one. Will
                        # continue until no more devices or the plugin throws an exception.
                        self.logger.debug(u"{0}: Channel updating...".format(dev.name))
                        self.devPrepareForThingspeak(dev, thing_dict)

                    except Exception:
                        self.Fogbert.pluginErrorHandler(traceback.format_exc())
                        self.logger.debug("{0} - Curl Return Code: {1}".format(dt.datetime.time(dt.datetime.now()),
                                                                               response))
                        self.logger.debug("{0} - Curl Response Dict: {1}".format(dt.datetime.time(dt.datetime.now()),
                                                                                 response_dict,))

                else:
                    continue

        self.uploadNow = False  # If we've come here manually
        self.updating  = False  # If we've come here automatically
        return

    # =============================================================================
    def listGenerator(self, filter="", values_dict=None, type_id="", target_id=0):
        """
        Return a list of devices and variables

        The listGenerator() method returns the current list of devices and
        variables from the list 'self.devicesAndVariablesList'.

        -----

        :param filter:
        :param values_dict:
        :param type_id:
        :param target_id:
        """

        return self.devicesAndVariablesList

    # =============================================================================
    def onlyNumerics(self, val):
        """
        Ensure value is a number

        This method evaluates values intended for upload. It ensures that the
        values are numeric only (i.e., stripping °F) and converting binary
        strings to integers. It also converts Indigo string values to floats
        as necessary.

        -----

        :param val:
        """

        try:
            # Does it float? Yes? Then it must be a witch.
            return float(val)

        # If it doesn't float, let's see if it's a boolean or a string that contains a
        # number.
        except ValueError:

            # Bool maybe?
            if val.upper() in ("TRUE", "ON"):
                return 1

            elif val.upper() in ("FALSE", "OFF"):
                return 0

            # Is it a string that contains a number?
            else:
                val = val.upper()
                val1 = ''.join([_ for _ in val if _ in '1234567890.'])

                if len(val1) != 0:
                    return val1

                else:
                    return False

    # =============================================================================
    def sendToThingspeak(self, request_type, url, parms):
        """
        Send the payload to Thingspeak

        The sendToThingspeak() method is called by several methods when data needs to
        be uploaded or downloaded. It returns a response code and a json dict (or
        returns an empty dict if no json is received.

        -----

        :param request_type:
        :param url:
        :param parms:
        :return response.code, response_dict:
        """

        response      = ""
        response_dict = {}
        response_code = 0

        self.logger.debug(u"Warning! Debug output contains sensitive information.")

        # Build upload URL.
        if self.pluginPrefs['devicePort']:
            ts_ip = self.pluginPrefs['deviceIP']
        else:
            ts_ip = "api.thingspeak.com"

        url = "https://{0}{1}".format(ts_ip, url)

        try:
            if request_type == "put":
                response = requests.put(url, params=parms, timeout=10)
            elif request_type == "get":
                response = requests.get(url, params=parms, timeout=10)
            elif request_type == "post":
                response = requests.post(url, params=parms, timeout=10)
            elif request_type == "delete":
                response = requests.delete(url, params=parms, timeout=10)

            self.logger.debug(url)

            try:
                response_dict = response.json()
            except Exception:
                response_dict = {}

            response_code = response.status_code

            self.logger.debug(u"Result: {0}".format(response_dict))

            if response_code == 200:
                return response_code, response_dict

            else:
                response_error_msg_dict = {400: u"The request cannot be fulfilled due to bad syntax.",
                                           401: u"Please provide proper authentication details.",
                                           402: u"You have exceeded the message limit for the ThingSpeak™ license.",
                                           405: u"Please use the proper HTTP method for this request.",
                                           413: u"Your request is too large. Please reduce the size and try again.",
                                           421: u"The server attempted to process your request, but has no action to perform.",
                                           429: u"Server busy. Please wait before making another request.",
                                           }

                self.logger.warning(response_error_msg_dict.get(response.status_code, u"Error unknown."))
                return response_code, response_dict

        # Internet isn't there
        except requests.exceptions.ConnectionError:
            self.Fogbert.pluginErrorHandler(traceback.format_exc())
            self.logger.warning(u"Unable to reach host. Will continue to attempt connection.")

            # TODO: this has been throwing gremlins in Little Snitch
            # Attempt ping every 30 seconds until Internet comes back
            while response != 0:
                response = os.system("/sbin/ping -c 1 google.com")
                self.sleep(30)

            return response_code, response_dict

        # ThingSpeak doesn't respond
        except requests.exceptions.Timeout:
            self.Fogbert.pluginErrorHandler(traceback.format_exc())
            self.logger.warning(u"Host server timeout. Will continue to retry.")
            return response_code, response_dict

    # =============================================================================
    def updateMenuConfigUi(self, values_dict, menu_id):
        """
        Populate controls in the Update Channel Info... configuration dialog

        the updateMenuConfigUi method generates the needed lists to populate controls
        that are displayed in the configuration menu for updating channel information.
        This process is real time; that is, the plugin will reach out to Thingspeak to
        get the latest information in case it has been changed using the web client or
        other means.

        -----

        :param values_dict:
        :param menu_id:
        :return values_dict:
        """

        if menu_id == 'channelUpdate':
            url       = "/channels.json"
            parms     = {'api_key': self.pluginPrefs.get('apiKey', '')}
            write_key = ""

            response, response_dict = self.sendToThingspeak('get', url, parms)

            for thing in response_dict:
                if thing['id'] == int(values_dict['channelList']):
                    values_dict['description'] = thing['description']
                    values_dict['metadata']    = thing['metadata']
                    values_dict['name']        = thing['name']
                    values_dict['tags']        = ",".join([tag['name'] for tag in thing['tags']])
                    values_dict['url']         = thing['url']
                    values_dict['public_flag'] = thing['public_flag']

                    self.logger.debug(u"Channel Info: {0}".format(thing))
                    write_key = thing['api_keys'][0]['api_key']

            url   = "/channels/{0}/feeds.json".format(int(values_dict['channelList']))
            parms = {'api_key': write_key}

            response, response_dict = self.sendToThingspeak('get', url, parms)

            # For thing values 1-8
            for _ in range(1, 9):
                values_dict['field{0}'.format(_)] = response_dict['channel'].get('field{0}'.format(_), '')

        return values_dict

    # =============================================================================
    def updateThingspeakDataAction(self, values_dict):
        """
        Update Thingspeak data based on a plugin action item call

        The updateThingspeakDataAction () method invokes an instantaneous
        update of the Thingspeak data channels. If this is called before 15
        seconds have elapsed since the last update, Thingspeak will ignore it.
        Unsure if the 15 second limit starts over.

        -----

        :param values_dict:
        """

        self.uploadNow = True
        self.encodeValueDicts()
        return

    # =============================================================================
    def updateThingspeakDataMenu(self):
        """
        Update Thingspeak data based on a plugin menu item call

        The updateThingspeakDataMenu() method invokes an instantaneous update
        of the Thingspeak data channels. If this is called before 15 seconds
        have elapsed since the last update, Thingspeak will ignore it. Unsure
        if the 15 second limit starts over.

        -----

        """

        self.uploadNow = True
        self.encodeValueDicts()
        return
    # =============================================================================
