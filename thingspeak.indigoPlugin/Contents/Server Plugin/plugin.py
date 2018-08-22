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
 - Update Checker by: berkinet (with additional features by Travis Cook)

Thingspeak API - https://www.mathworks.com/help/thingspeak/
"""

# =================================== TO DO ===================================


# ================================== IMPORTS ==================================

# Built-in modules
from dateutil.parser import parse as du_parse
import datetime as dt
import logging
import os
import pytz
import requests
import time as t

# Third-party modules
from DLFramework import indigoPluginUpdateChecker
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
__version__   = '1.2.02'

# =============================================================================

kDefaultPluginPrefs = {
    u'configMenuTimeoutInterval': 15,            # How long to wait on a server timeout.
    u'elevation'                : 0,             # Elevation of data source.
    u'latitude'                 : 0,             # Latitude of data source.
    u'longitude'                : 0,             # Longitude of data source.
    u'showDebugInfo'            : False,         # Verbose debug logging?
    u'showDebugLevel'           : 1,             # Low, Medium or High debug output.
    u'twitter'                  : "",            # Username linked to ThingTweet
    u'updaterEmail'             : "",            # Email to notify of plugin updates.
    u'updaterEmailsEnabled'     : False,         # Notification of plugin updates wanted.
    }


class Plugin(indigo.PluginBase):
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.pluginIsInitializing = True
        self.pluginIsShuttingDown = False

        updater_url               = "https://raw.githubusercontent.com/DaveL17/thingspeak/master/thingspeak_version.html"
        self.updater              = indigoPluginUpdateChecker.updateChecker(self, updater_url)
        self.updaterEmail         = self.pluginPrefs.get('updaterEmail', "")
        self.updaterEmailsEnabled = self.pluginPrefs.get('updaterEmailsEnabled', "false")

        # ============================ Configure Logging ==============================
        # Convert from legacy ['low', 'medium', 'high'] or [1, 2, 3].
        try:
            if int(self.pluginPrefs.get('showDebugLevel', '30')) < 10:
                self.pluginPrefs['showDebugLevel'] *= 10
        except ValueError:
            self.pluginPrefs['showDebugLevel'] = 30

        self.debugLevel = self.pluginPrefs['showDebugLevel']
        self.plugin_file_handler.setFormatter(logging.Formatter('%(asctime)s.%(msecs)03d\t%(levelname)-10s\t%(name)s.%(funcName)-28s %(msg)s', datefmt='%Y-%m-%d %H:%M:%S'))
        self.indigo_log_handler.setLevel(self.debugLevel)

        self.logFileDate    = pluginPrefs.get('logFileDate', "1970-01-01")
        self.logFile        = pluginPrefs.get('logFileLocation', "/Library/Application Support/Perceptive Automation/Indigo {0}/Logs/Thingspeak Log.txt".format(indigo.server.version[0]))
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

        self.pluginIsInitializing = False

    def __del__(self):

        indigo.PluginBase.__del__(self)

# Indigo Methods ==============================================================

    def closedPrefsConfigUi(self, valuesDict, userCancelled):

        if userCancelled:
            self.logger.debug(u"User prefs dialog cancelled.")

        if not userCancelled:
            self.logger.debug(u"User prefs saved.")
            self.logger.debug(unicode(valuesDict))

            self.logger.warning(u"Warning! Debug output contains sensitive information.")

        # Update update select globals if plugin prefs have changed.
        self.debugLevel = int(self.pluginPrefs.get('showDebugLevel', '30'))
        self.indigo_log_handler.setLevel(self.debugLevel)

    def deviceStartComm(self, dev):

        self.logger.debug(u"Starting device: {0}".format(dev.name))
        dev.stateListOrDisplayStateIdChanged()
        dev.updateStateOnServer('thingState', value=False, uiValue=u"waiting")
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def deviceStopComm(self, dev):

        self.logger.debug(u"Stopping device: {0}".format(dev.name))
        dev.updateStateOnServer('thingState', value=False, uiValue=u"disabled")
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def getDeviceConfigUiValues(self, valuesDict, typeId, devId):

        # Get latest list of Indigo devices and variables. We don't return
        # it from here, but we want it updated any time a device config is
        # opened.
        self.devicesAndVariablesList = self.Fogbert.deviceAndVariableList()

        return valuesDict

    def runConcurrentThread(self):

        self.logger.debug(u"runConcurrentThread() initiated.")

        try:
            while True:
                self.updater.checkVersionPoll()

                if not self.updating and not self.uploadNow:
                    self.updating = True
                    self.encodeValueDicts()

                # We check every 2 seconds to see if any devices need updating.
                self.sleep(2)

        except self.StopThread:
            self.logger.debug(u"Thingspeak stop thread called.")
            pass

    def startup(self):

        # Notify users they can safely delete legacy custom log file.
        if int(__version__.split('.')[1]) < 2:
            indigo.server.log(u"*" * 80)
            indigo.server.log(u"Custom log file feature no longer supported. You can safely delete the log file.")
            indigo.server.log(u"Log file location: {0}".format(self.pluginPrefs['logFileLocation']))
            indigo.server.log(u"*" * 80)

        self.logger.warning(u"Warning! Debug output contains sensitive information.")
        self.updater.checkVersionPoll()  # See if there is an update and whether the user wants to be notified.

    def shutdown(self):

        self.pluginIsShuttingDown = True

        for dev in indigo.devices.iter('self'):
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def validatePrefsConfigUi(self, valuesDict):

        error_msg_dict = indigo.Dict()

        # ================================= API Key ===================================
        # Key must be 16 characters in length
        if len(valuesDict['apiKey']) not in (0, 16):
            error_msg_dict['apiKey'] = u"The API Key must be 16 characters long."
            error_msg_dict['showAlertText'] = u"API Key Error:\n\nThe API Key must be 16 characters long and cannot contain spaces."
            return False, valuesDict, error_msg_dict

        # Test key against ThingSpeak service
        if not valuesDict['devicePort']:
            try:
                ts_ip = "https://api.thingspeak.com/channels.json?api_key={0}".format(valuesDict['apiKey'])
                response = requests.get(ts_ip, timeout=1.50)

                if response.status_code == 401:
                    raise ValueError

            except requests.exceptions.Timeout:
                self.logger.warning(u"Unable to confirm accuracy of API Key with the ThingSpeak service.")

            except ValueError:
                error_msg_dict['apiKey'] = u"Invalid API Key"
                error_msg_dict['showAlertText'] = u"API Key Error:\n\nThingSpeak rejected your API Key as invalid. Please ensure that your key is entered correctly."
                return False, valuesDict, error_msg_dict

        # ============================ Latitude / Longitude ===========================
        # Must be integers or floats. Can be negative.
        try:
            float(valuesDict['latitude'])
        except ValueError:
            error_msg_dict['latitude'] = u"Please enter a number (positive, negative or zero)."
            error_msg_dict['showAlertText'] = u"Latitude Error:\n\nThingspeak requires latitude to be expressed as a number. It can be positive, negative or zero."
            valuesDict['latitude'] = 0.0
            return False, valuesDict, error_msg_dict

        try:
            float(valuesDict['longitude'])
        except ValueError:
            error_msg_dict['longitude'] = u"Please enter a number (positive, negative or zero)."
            error_msg_dict['showAlertText'] = u"Longitude Error:\n\nThingspeak requires longitude to be expressed as a number. It can be positive, negative or zero."
            valuesDict['longitude'] = 0.0
            return False, valuesDict, error_msg_dict

        # ================================= Elevation =================================
        # Must be an integer (can not be a float. Can be negative.
        try:
            int(valuesDict['elevation'])
        except ValueError:
            error_msg_dict['elevation'] = u"Please enter a whole number integer (positive, negative or zero)."
            error_msg_dict['showAlertText'] = u"Elevation Error:\n\nThingspeak requires elevation to be expressed as a whole number integer. It can be positive, negative or zero."
            valuesDict['elevation'] = 0
            return False, valuesDict, error_msg_dict

        if "." in str(valuesDict['elevation']):
            error_msg_dict['elevation'] = u"Please enter a whole number integer (positive, negative or zero)."
            error_msg_dict['showAlertText'] = u"Elevation Error:\n\nThingspeak requires elevation to be expressed as a whole number integer. It can be positive, negative or zero."
            valuesDict['elevation'] = 0
            return False, valuesDict, error_msg_dict

        # =============================== Notifications ===============================
        if valuesDict['updaterEmailsEnabled'] and not valuesDict['updaterEmail']:
            error_msg_dict['updaterEmail'] = u"Please supply a valid email address."
            error_msg_dict['showAlertText'] = u"Updater Email Error:\n\nThe plugin requires a valid email address in order to notify you of plugin updates."
            return False, valuesDict, error_msg_dict

        elif valuesDict['updaterEmailsEnabled'] and "@" not in valuesDict['updaterEmail']:
            error_msg_dict['updaterEmail'] = u"Please supply a valid email address."
            error_msg_dict['showAlertText'] = u"Updater Email Error:\n\nThe plugin requires a valid email address in order to notify you of plugin updates (the email address needs " \
                                              u"an '@' symbol."
            return False, valuesDict, error_msg_dict

        return True, valuesDict

# Plugin Methods ==============================================================

    def channelListGenerator(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Generate a list of channel names and IDs

        The channelListGenerator() method generates a list of channel names
        and IDs which are used to identify the target channel.

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        :return: [(channel_id, channel_name), (channel_id, channel_name)]
        """

        url   = "/channels.json"
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('get', url, parms)

        return [(item['id'], item['name']) for item in response_dict]

    def channelClearFeed(self, valuesDict, typeId):
        """
        Clear Thingspeak channel using Thingspeak API

        The channelClearFeed() method is called when a user selects 'Clear
        Channel Data' from the plugin menu. It is used to clear all data from
        the channel (the channel remains intact.

        -----

        :param valuesDict:
        :param typeId:
        """

        url = "/channels/{0}/feeds.xml".format(valuesDict['channelList'])
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('delete', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully cleared.".format(response))
        else:
            self.logger.warning(u"Problem clearing channel data.")

        return True

    def channelDelete(self, valuesDict, typeId):
        """
        Delete Thingspeak channel using Thingspeak API

        The channelDelete() method is called when a user selects 'Delete
        a Channel' from the plugin menu. It is used to delete a channel from
        Thingspeak.

        -----

        :param valuesDict:
        :param typeId:
        :return bool:
        """

        url = "/channels/{0}.xml".format(valuesDict['channelList'])
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('delete', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully deleted.".format(response))
        else:
            self.logger.warning(u"Problem deleting channel data.")

        return True

    def getParms(self, valuesDict):
        """
        Construct the API URL for upload to Thingspeak

        Construct the values needed for the data upload to the Thingspeak server.

        -----

        :param valuesDict:
        """

        # Thingspeak requires a string representation of the boolean value.
        if valuesDict['public_flag']:
            public_flag = 'true'
        else:
            public_flag = 'false'

        parms = {'api_key':     self.pluginPrefs.get('apiKey', ''),    # User's API key. This is different from a channel API key, and can be found in account profile page. (required).
                 'elevation':   self.pluginPrefs.get('elevation', 0),  # Elevation in meters (optional)
                 'latitude':    self.pluginPrefs.get('latitude', 0),   # Latitude in degrees (optional)
                 'longitude':   self.pluginPrefs.get('longitude', 0),  # Longitude in degrees (optional)
                 'description': valuesDict['description'],             # Description of the channel (optional)
                 'field1':      valuesDict['field1'],                  # Field 1 name (optional)
                 'field2':      valuesDict['field2'],                  # Field 2 name (optional)
                 'field3':      valuesDict['field3'],                  # Field 3 name (optional)
                 'field4':      valuesDict['field4'],                  # Field 4 name (optional)
                 'field5':      valuesDict['field5'],                  # Field 5 name (optional)
                 'field6':      valuesDict['field6'],                  # Field 6 name (optional)
                 'field7':      valuesDict['field7'],                  # Field 7 name (optional)
                 'field8':      valuesDict['field8'],                  # Field 8 name (optional)
                 'metadata':    valuesDict['metadata'],                # Metadata for the channel, which can include JSON, XML, or any other data (optional)
                 'name':        valuesDict['name'],                    # Name of the channel (optional)
                 'public_flag': public_flag,                           # Whether the channel is public, default 'false' (optional, string required if present)
                 'tags':        valuesDict['tags'],                    # Comma-separated list of tags (optional)
                 'url':         valuesDict['url'],                     # Web page URL for the channel (optional)
                 }

        return parms

    def channelCreate(self, valuesDict, typeId):
        """
        Create Thingspeak channel using Thingspeak API

        The channelCreate() method is called when a user selects 'Create a
        Channel' from the plugin menu. It is used to create a new channel on
        Thingspeak.

        -----

        :param valuesDict:
        :param typeId:
        """

        url = "/channels.json"

        parms = self.getParms(valuesDict)

        response, response_dict = self.sendToThingspeak('post', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully created.".format(response))
            return True
        else:
            self.logger.warning(u"Problem creating channel.")
            return False

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
            indigo.server.log(u"{0:<8}{1:<25}{2:^9}{3:<21}{4:^10}{5:<18}".format('ID', 'Name', 'Public', 'Created At', 'Ranking', 'Write Key'))
            indigo.server.log(u"{0:=^100}".format(""))
            for thing in response_dict:
                for key in thing['api_keys']:
                    if key['write_flag']:
                        write_key = key['api_key']
                indigo.server.log(u"{0:<8}{1:<25}{2:^9}{3:<21}{4:^10}{5:<18}".format(thing['id'], thing['name'], thing['public_flag'], thing['created_at'], thing['ranking'], write_key))

            return True

        else:
            return False

    def channelUpdate(self, valuesDict, typeId):
        """
        Update Thingspeak channel using Thingspeak API

        The channelUpdate() method is called when a user selects 'Update
        a Channel' from the plugin menu. It is used to make changes to channel
        settings.

        -----

        :param valuesDict:
        :param typeId:
        """

        url = "/channels/{0}.json".format(valuesDict['channelList'])

        # Validation
        if not valuesDict['channelList']:
            error_msg_dict = indigo.Dict()
            error_msg_dict['channelList'] = u"Please select a channel to update."
            error_msg_dict['showAlertText'] = u"Update Channel Info Error:\n\nYou must select a channel to update."
            return False, valuesDict, error_msg_dict

        parms = self.getParms(valuesDict)

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
            return False, valuesDict

    def checkPluginVersion(self):
        """
        Check to see if running the most current version of the plugin.

        The checkPluginVersion() method will reach out to determine whether
        the plugin version is current.

        -----

        """

        self.updater.checkVersionNow()

    def commsKillAll(self):
        """
        Disable communication for all plugin devices

        commsKillAll() sets the enabled status of all plugin devices to
        false.

        -----

        """

        for dev in indigo.devices.itervalues("self"):
            indigo.device.enable(dev, value=False)

    def commsUnkillAll(self):
        """
        Enable communication for all plugin devices

        commsUnkillAll() sets the enabled status of all plugin devices
        to true.

        -----

        """

        for dev in indigo.devices.itervalues("self"):
            indigo.device.enable(dev, value=True)

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

    def devStateGenerator1(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        The following eight methods produce lists of states that are associated
        with user-selected devices when configuring Thingspeak reporting
        devices. Each list includes only states for the selected device.

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        """

        if not valuesDict:
            return []

        if valuesDict and "thing1" in valuesDict:
            if valuesDict['thing1'] != "":
                try:
                    if int(valuesDict['thing1']) in indigo.devices:
                        dev = indigo.devices[int(valuesDict['thing1'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(valuesDict['thing1']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    def devStateGenerator2(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        """

        if not valuesDict:
            return []

        if valuesDict and "thing2" in valuesDict:

            # If an item has been selected.
            if valuesDict['thing2'] != "":
                try:
                    if int(valuesDict['thing2']) in indigo.devices:
                        dev = indigo.devices[int(valuesDict['thing2'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(valuesDict['thing2']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    def devStateGenerator3(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        """

        if not valuesDict:
            return []

        if valuesDict and "thing3" in valuesDict:
            if valuesDict['thing3'] != "":
                try:
                    if int(valuesDict['thing3']) in indigo.devices:
                        dev = indigo.devices[int(valuesDict['thing3'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(valuesDict['thing3']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    def devStateGenerator4(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        """

        if not valuesDict:
            return []

        if valuesDict and "thing4" in valuesDict:
            if valuesDict['thing4'] != "":
                try:
                    if int(valuesDict['thing4']) in indigo.devices:
                        dev = indigo.devices[int(valuesDict['thing4'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(valuesDict['thing4']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    def devStateGenerator5(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        """

        if not valuesDict:
            return []

        if valuesDict and "thing5" in valuesDict:
            if valuesDict['thing5'] != "":
                try:
                    if int(valuesDict['thing5']) in indigo.devices:
                        dev = indigo.devices[int(valuesDict['thing5'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(valuesDict['thing5']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    def devStateGenerator6(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        """

        if not valuesDict:
            return []

        if valuesDict and "thing6" in valuesDict:
            if valuesDict['thing6'] != "":
                try:
                    if int(valuesDict['thing6']) in indigo.devices:
                        dev = indigo.devices[int(valuesDict['thing6'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(valuesDict['thing6']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    def devStateGenerator7(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        """

        if not valuesDict:
            return []

        if valuesDict and "thing7" in valuesDict:
            if valuesDict['thing7'] != "":
                try:
                    if int(valuesDict['thing7']) in indigo.devices:
                        dev = indigo.devices[int(valuesDict['thing7'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(valuesDict['thing7']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

    def devStateGenerator8(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Generate a list of devices and variables for the Thingspeak device

        See Docstring for devStateGenerator1

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        """

        if not valuesDict:
            return []

        if valuesDict and "thing8" in valuesDict:
            if valuesDict['thing8'] != "":
                try:
                    if int(valuesDict['thing8']) in indigo.devices:
                        dev = indigo.devices[int(valuesDict['thing8'])]
                        return [x for x in dev.states.keys() if ".ui" not in x]
                    elif int(valuesDict['thing8']) in indigo.variables:
                        return [('value', 'value')]
                    else:
                        return [('None', 'None')]
                except ValueError:
                    return [('None', 'None')]
            else:
                return [('None', 'None')]

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
                indigo.server.log(u"A device is being (or has been) created, but it's not fully configured. Sleeping while you finish.")
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
                                    self.logger.warning(u"{0} - {1} is non-numeric or has been removed. Will try to upload, but it won't chart.".format(dev.name, dev.pluginProps[thing_str]))
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
                                    self.logger.warning(u"{0} - {1} is non-numeric or has been removed. Will try to upload, but it won't chart.".format(dev.name, dev.pluginProps[thing_str]))

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

                    except Exception as error:

                        f = open(self.logFile, 'a')
                        f.write("{0} - Curl Return Error: {1}\n".format(dt.datetime.time(dt.datetime.now()), error))
                        f.write("{0} - Curl Return Code: {1}\n".format(dt.datetime.time(dt.datetime.now()), response))
                        f.write("{0} - Curl Response Dict: {1}\n\n".format(dt.datetime.time(dt.datetime.now()), response_dict))
                        f.close()

                        self.logger.warning(unicode(error))
                else:
                    continue

        self.uploadNow = False  # If we've come here manually
        self.updating  = False  # If we've come here automatically
        return

    def listGenerator(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        Return a list of devices and variables

        The listGenerator() method returns the current list of devices and
        variables from the list 'self.devicesAndVariablesList'.

        -----

        :param filter:
        :param valuesDict:
        :param typeId:
        :param targetId:
        """

        return self.devicesAndVariablesList

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
            except:
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
            self.logger.warning(u"Unable to reach host. Will continue to attempt connection.")

            # TODO: this has been throwing gremlins in Little Snitch
            # Attempt ping every 30 seconds until Internet comes back
            while response != 0:
                response = os.system("/sbin/ping -c 1 google.com")
                self.sleep(30)

            return response_code, response_dict

        # ThingSpeak doesn't respond
        except requests.exceptions.Timeout:
            self.logger.warning(u"Host server timeout. Will continue to retry.")
            return response_code, response_dict

    def updateMenuConfigUi(self, valuesDict, menuId):
        """
        Populate controls in the Update Channel Info... configuration dialog

        the updateMenuConfigUi method generates the needed lists to populate controls
        that are displayed in the configuration menu for updating channel information.
        This process is real time; that is, the plugin will reach out to Thingspeak to
        get the latest information in case it has been changed using the web client or
        other means.

        -----

        :param valuesDict:
        :param menuId:
        :return valuesDict:
        """

        if menuId == 'channelUpdate':
            url       = "/channels.json"
            parms     = {'api_key': self.pluginPrefs.get('apiKey', '')}
            write_key = ""

            response, response_dict = self.sendToThingspeak('get', url, parms)

            for thing in response_dict:
                if thing['id'] == int(valuesDict['channelList']):
                    valuesDict['description'] = thing['description']
                    valuesDict['metadata']    = thing['metadata']
                    valuesDict['name']        = thing['name']
                    valuesDict['tags']        = ",".join([tag['name'] for tag in thing['tags']])
                    valuesDict['url']         = thing['url']
                    valuesDict['public_flag'] = thing['public_flag']

                    self.logger.debug(u"Channel Info: {0}".format(thing))
                    write_key = thing['api_keys'][0]['api_key']

            url   = "/channels/{0}/feeds.json".format(int(valuesDict['channelList']))
            parms = {'api_key': write_key}

            response, response_dict = self.sendToThingspeak('get', url, parms)

            # For thing values 1-8
            for _ in range(1, 9):
                valuesDict['field{0}'.format(_)] = response_dict['channel'].get('field{0}'.format(_), '')

        return valuesDict

    def updateThingspeakDataAction(self, valuesDict):
        """
        Update Thingspeak data based on a plugin action item call

        The updateThingspeakDataAction () method invokes an instantaneous
        update of the Thingspeak data channels. If this is called before 15
        seconds have elapsed since the last update, Thingspeak will ignore it.
        Unsure if the 15 second limit starts over.

        -----

        :param valuesDict:
        """

        self.uploadNow = True
        self.encodeValueDicts()
        return

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
