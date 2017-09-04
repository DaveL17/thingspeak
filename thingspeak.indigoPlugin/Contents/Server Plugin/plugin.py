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


`Thingspeak Plugin <https://davel17.github.io/thingspeak/>`_

`Indigo Domotics <http://www.indigodomo.com>`_

"""

# TODO:

import datetime as dt
import indigoPluginUpdateChecker
import os.path
import pydevd
import requests
import sys
import time as t

try:
    import indigo
except ImportError:
    pass

__author__    = "DaveL17"
__build__     = ""
__copyright__ = 'Copyright 2017 DaveL17'
__license__   = "MIT"
__title__     = 'Thingspeak Plugin for Indigo Home Control'
__version__   = '1.1.01'

kDefaultPluginPrefs = {
    u'configMenuTimeoutInterval': 15,            # How long to wait on a server timeout.
    u'elevation'                : 0,             # Elevation of data source.
    u'latitude'                 : 0,             # Latitude of data source.
    u'logFileDate'              : "1970-01-01",  # Log file creation date.
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

        indigo.server.log(u"")
        indigo.server.log(u"{0:=^130}".format(" Initializing New Plugin Session "))
        indigo.server.log(u"{0:<31} {1}".format("Plugin name:", pluginDisplayName))
        indigo.server.log(u"{0:<31} {1}".format("Plugin version:", pluginVersion))
        indigo.server.log(u"{0:<31} {1}".format("Plugin ID:", pluginId))
        indigo.server.log(u"{0:<31} {1}".format("Indigo version:", indigo.server.version))
        indigo.server.log(u"{0:<31} {1}".format("Python version:", sys.version.replace('\n', '')))
        indigo.server.log(u"{0:=^130}".format(""))

        self.debug          = pluginPrefs['showDebugInfo']
        self.debugLevel     = pluginPrefs['showDebugLevel']
        self.devicesAndVariablesList = []
        self.logFileDate    = pluginPrefs.get('logFileDate', "1970-01-01")
        self.logFile        = pluginPrefs['logFileLocation']
        updater_url         = "https://davel17.github.io/thingspeak/thingspeak_version.html"
        self.updater        = indigoPluginUpdateChecker.updateChecker(self, updater_url)

        # Create the log file location if it doesn't exist.
        split_path = os.path.split(pluginPrefs['logFileLocation'])
        if not os.path.exists(split_path[0]):
            self.debugLog(u"Log file location doesn't exist. Attempting to create it.")
            os.makedirs(split_path[0])

        # pydevd.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True, suspend=False)  # To enable remote PyCharm Debugging, uncomment this line.

    def __del__(self):

        indigo.PluginBase.__del__(self)

    # Indigo Methods ==========================================================

    def closedPrefsConfigUi(self, valuesDict, userCancelled):

        self.debugLog(u"closedPrefsConfigUi() called.")

        if userCancelled:
            self.debugLog(u"User prefs dialog cancelled.")

        if not userCancelled:
            self.debug = valuesDict.get('showDebugInfo', False)
            self.debugLog(u"User prefs saved.")
            if self.pluginPrefs['showDebugLevel'] >= 3:
                self.debugLog(unicode(valuesDict))

            if self.debug:
                indigo.server.log(u"Debug logging is on.")
                if self.debugLevel >= 3:
                    self.debugLog(u"Warning! Debug set to high. Sensitive information will be sent to the Indigo log.")

        # Update update select globals if plugin prefs have changed.
        self.debugLevel     = self.pluginPrefs.get('showDebugLevel', 1)

    def deviceStartComm(self, dev):

        self.debugLog(u"deviceStartComm() called. Device: {0}".format(dev.name))
        dev.stateListOrDisplayStateIdChanged()
        dev.updateStateOnServer('thingState', value=False, uiValue=u"waiting")
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def deviceStopComm(self, dev):

        self.debugLog(u"deviceStopComm() called. Device: {0}".format(dev.name))
        dev.updateStateOnServer('thingState', value=False, uiValue=u"disabled")
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def getDeviceConfigUiValues(self, valuesDict, typeId, devId):

        self.debugLog(u"getDeviceConfigUiValues() called.")

        self.devicesAndVariablesList = []
        [self.devicesAndVariablesList.append((dev.id, u"(D) {0}".format(dev.name))) for dev in indigo.devices]
        [self.devicesAndVariablesList.append((var.id, u"(V) {0}".format(var.name))) for var in indigo.variables]
        self.devicesAndVariablesList.append(('None', 'None'))

        return valuesDict

    # def getMenuActionConfigUiValues(self, menuId):
    #     """"""
    #     self.debugLog(u"getMenuActionConfigUiValues(self, menuId) called.")
    #
    #     valuesDict = indigo.Dict()
    #
    #     return valuesDict

    def runConcurrentThread(self):

        self.debugLog(u"runConcurrentThread() initiated.")

        try:
            while True:
                # self.sleep(1)
                self.updater.checkVersionPoll()
                self.checkDebugLogFile()
                self.encodeValueDicts()

                # We check every 2 seconds to see if any devices need updating.
                self.sleep(2)

        except self.StopThread:
            self.debugLog(u"Thingspeak stop thread called.")
            pass

    def startup(self):

        self.debugLog(u"startup() method called.")

        if self.debug and self.debugLevel >= 3:
            self.debugLog(u"Warning! Debug set to high. Sensitive information will be sent to the Indigo log.")

        self.updater.checkVersionPoll()  # See if there is an update and whether the user wants to be notified.

    def shutdown(self):

        self.debugLog(u"shutdown() method called.")

        for dev in indigo.devices.iter('self'):
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def validatePrefsConfigUi(self, valuesDict):

        self.debugLog(u"validatePrefsConfigUi() called.")

        error_msg_dict = indigo.Dict()

        try:
            try:
                if len(valuesDict['apiKey']) not in (0, 16):
                    raise Exception
            except ValueError:
                error_msg_dict['apiKey'] = u"The API Key must be 16 characters long."
                error_msg_dict['showAlertText'] = u"API Key Error:\n\nThe API Key must be 16 characters long and cannot contain spaces."
                return False, valuesDict, error_msg_dict

            # Test latitude and longitude. Must be integers or floats. Can be negative.
            try:
                float(valuesDict['latitude'])
            except ValueError:
                error_msg_dict['latitude'] = u"Please enter a number (positive, negative or zero)."
                error_msg_dict['showAlertText'] = u"Latitude Error:\n\nThingspeak requires latitude to be expressed as a number. It can be positive, negative or zero."
                valuesDict['latitude'] = 0
                return False, valuesDict, error_msg_dict

            try:
                float(valuesDict['longitude'])
            except ValueError:
                error_msg_dict['longitude'] = u"Please enter a number (positive, negative or zero)."
                error_msg_dict['showAlertText'] = u"Longitude Error:\n\nThingspeak requires longitude to be expressed as a number. It can be positive, negative or zero."
                valuesDict['longitude'] = 0
                return False, valuesDict, error_msg_dict

            # Test elevation. Must be an integer (can not be a float. Can be negative.
            try:
                int(valuesDict['elevation'])
            except ValueError:
                error_msg_dict['elevation'] = u"Please enter a whole number integer (positive, negative or zero)."
                error_msg_dict['showAlertText'] = u"Elevation Error:\n\nThingspeak requires elevation to be expressed as a whole number integer. It can be positive, negative or zero."
                valuesDict['elevation'] = 0
                return False, valuesDict, error_msg_dict

            if "." in valuesDict['elevation']:
                error_msg_dict['elevation'] = u"Please enter a whole number integer (positive, negative or zero)."
                error_msg_dict['showAlertText'] = u"Elevation Error:\n\nThingspeak requires elevation to be expressed as a whole number integer. It can be positive, negative or zero."
                valuesDict['elevation'] = 0
                return False, valuesDict, error_msg_dict

            # Test plugin update notification settings.
            if valuesDict['updaterEmailsEnabled'] and not valuesDict['updaterEmail']:
                error_msg_dict['updaterEmail'] = u"Please supply a valid email address."
                error_msg_dict['showAlertText'] = u"Updater Email Error:\n\nThe plugin requires a valid email address in order to notify you of plugin updates."
                return False, valuesDict, error_msg_dict

            elif valuesDict['updaterEmailsEnabled'] and "@" not in valuesDict['updaterEmail']:
                error_msg_dict['updaterEmail'] = u"Please supply a valid email address."
                error_msg_dict['showAlertText'] = u"Updater Email Error:\n\nThe plugin requires a valid email address in order to notify you of plugin updates (the email address needs " \
                                                  u"an '@' symbol."
                return False, valuesDict, error_msg_dict

            # Test log file location setting.
            if not valuesDict['logFileLocation'] or valuesDict['logFileLocation'].isspace():
                error_msg_dict['logFileLocation'] = u"Please supply a valid log file location."
                error_msg_dict['showAlertText'] = u"Log File Location Error:\n\nThe plugin requires a valid location to save log data."
                return False, valuesDict, error_msg_dict

            # Create the path to the log file location if it doesn't exist yet.
            split_path = os.path.split(valuesDict['logFileLocation'])
            if not os.path.exists(split_path[0]):
                os.makedirs(split_path[0])

        except Exception as error:

            f = open(self.logFile, 'a')
            f.write("{0} - validatePrefsConfigUi error: {1}\n".format(dt.datetime.time(dt.datetime.now()), error))
            f.close()

            self.debugLog(u"Exception in validatePrefsConfigUi tests: {0}".format(error))
            pass

        return True, valuesDict

    # Plugin Methods ==========================================================

    def channelListGenerator(self, filter="", valuesDict=None, typeId="", targetId=0):
        """ The channelListGenerator() method generates a list of channel names
        and IDs which are used to identify the target channel.

        :**url**: "/channels.json"
        :**parms**: {'api_key': self.pluginPrefs.get('apiKey', '')}
        :**return**: [(channel_id, channel_name), (channel_id, channel_name)] """

        self.debugLog(u'channelListGenerator() called.')

        url   = "/channels.json"
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('get', url, parms)

        return [(thing['id'], thing['name']) for thing in response_dict]

    def channelClearFeed(self, valuesDict, typeId):
        """ The channelClearFeed() method is called when a user selects 'Clear
        Channel Data' from the plugin menu. It is used to clear all data from
        the channel (the channel remains intact.
        """

        self.debugLog(u'channelClearFeed(self, valuesDict, typeId) called.')

        url = "/channels/{0}/feeds.xml".format(valuesDict['channelList'])
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('delete', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully cleared.".format(response))
        else:
            self.errorLog(u"Problem clearing channel data.")

        return True

    def channelDelete(self, valuesDict, typeId):
        """ The channelDelete() method is called when a user selects 'Delete
        a Channel' from the plugin menu. It is used to delete a channel from
        Thingspeak. """

        self.debugLog(u'channelDelete()')

        url = "/channels/{0}.xml".format(valuesDict['channelList'])
        parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

        response, response_dict = self.sendToThingspeak('delete', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully deleted.".format(response))
        else:
            self.errorLog(u"Problem clearing channel data.")

        return True

    def channelCreate(self, valuesDict, typeId):
        """ The channelCreate() method is called when a user selects 'Create a
        Channel' from the plugin menu. It is used to create a new channel on
        Thingspeak. """

        self.debugLog(u'channelCreate()')

        url = "/channels.json"

        parms = {'api_key':     self.pluginPrefs.get('apiKey', ''),    # User's API key. This is different from a channel API key, and can be found in your profile page. (required).
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
                 'public_flag': valuesDict['public_flag'],             # Whether the channel is public, default false (optional)
                 'tags':        valuesDict['tags'],                    # Comma-separated list of tags (optional)
                 'url':         valuesDict['url'],                     # Web page URL for the channel (optional)
                 }

        response, response_dict = self.sendToThingspeak('post', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully created.".format(response))
            return True
        else:
            self.errorLog(u"Problem creating channel.")
            return False

    def channelList(self):
        """ The channelList() method is called when a user selects 'List
        Channels' from the plugin menu. It is used to print a table of select
        channel information to the Indigo Events log. """

        self.debugLog(u'channelList()')

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
        """ The channelUpdate() method is called when a user selects 'Update
        a Channel' from the plugin menu. It is used to make changes to channel
        settings. """

        self.debugLog(u"channelUpdate() called.")
        url = "/channels/{0}.json".format(valuesDict['channelList'])

        # Validation
        if not valuesDict['channelList']:
            error_msg_dict = indigo.Dict()
            error_msg_dict['channelList'] = u"Please select a channel to update."
            error_msg_dict['showAlertText'] = u"Update Channel Info Error:\n\nYou must select a channel to update."
            return False, valuesDict, error_msg_dict

        # Thingspeak requires a string representation of the boolean value.
        if valuesDict['public_flag']:
            public_flag = 'true'
        else:
            public_flag = 'false'

        parms = {'api_key':     self.pluginPrefs.get('apiKey', ''),    # User's API key. This is different from a channel API key, and can be found in your profile page. (required).
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
                 'public_flag': public_flag,                           # Whether the channel is public, default false (optional)
                 'tags':        valuesDict['tags'],                    # Comma-separated list of tags (optional)
                 'url':         valuesDict['url'],                     # Web page URL for the channel (optional)
                 }

        # Get rid of empty key/value pairs so we don't overwrite existing information.
        for key in parms.keys():
            if parms[key] == "":
                del parms[key]

        response, response_dict = self.sendToThingspeak('put', url, parms)

        if response == 200:
            indigo.server.log(u"Channel successfully updated.".format(response))
            return True
        else:
            indigo.server.log(u"Problem updating channel settings.")
            return False, valuesDict

    def checkDebugLogFile(self):
        """
        The checkDebugLogFile() method manages the Thingspeak Plugin logging
        facility. It ensures the log file always exists and that it never
        contains more than one day of logs.
        """

        # self.debugLog(u"checkDebugLogFile() called.")  # This is commented out as it will appear in the log every 2 seconds.

        log      = dt.datetime.strptime(self.pluginPrefs.get('logFileDate', "1970-01-01"), "%Y-%m-%d")
        log_date = dt.datetime.date(log)
        now      = dt.datetime.now()
        today    = dt.datetime.date(now)

        # Create the log file if it doesn't exist or if it's a new day, delete the existing log file and create a new one.
        if not os.path.exists(self.logFile) or today > log_date:
            f = open(self.logFile, 'w')
            f.write(('*' * 72) + "\n")
            f.write("***{0}- Thingspeak Log - {1} - {2}***\n".format((' ' * 16), today, (' ' * 18)))
            f.write(('*' * 72) + "\n")
            f.close()

            self.pluginPrefs['logFileDate'] = str(today)  # Update plugin log date tracker with today's date.

    def checkPluginVersion(self):
        """ The checkPluginVersion() method will reach out to determine whether
         the plugin version is current. """

        self.debugLog(u"checkPluginVersion() called.")

        self.updater.checkVersionNow()

    def devKillAllComms(self):
        """ devKillAllComms() sets the enabled status of all plugin devices to
        false. """

        self.debugLog(u"devKillAllComms() called.")

        for dev in indigo.devices.itervalues("self"):
            indigo.device.enable(dev, value=False)

    def devPrepareForThingspeak(self, dev, parms):
        """
        This method performs the upload to Thingspeak, evaluates, and logs the
        result.
        """

        self.debugLog(u"devPrepareForThingspeak() called. Device: {0}".format(dev.name))

        url = "/update.json"

        response, response_dict = self.sendToThingspeak('post', url, parms)

        # Process the results.  Thingspeak will respond with a "0" if something went wrong.
        if response == 200:

            dev.updateStateOnServer('channel_id', value=int(response_dict.get('channel_id', "0")))
            dev.updateStateOnServer('elevation', value=int(response_dict.get('elevation', "0")))
            dev.updateStateOnServer('entry_id', value=int(response_dict.get('entry_id', "0")))
            dev.updateStateOnServer('latitude', value=float(response_dict.get('latitude', "0")))
            dev.updateStateOnServer('longitude', value=float(response_dict.get('longitude', "0")))
            dev.updateStateOnServer('status', value=response_dict.get('status', "0"))
            dev.updateStateOnServer('thing1', value=response_dict.get('field1', "0"))
            dev.updateStateOnServer('thing2', value=response_dict.get('field2', "0"))
            dev.updateStateOnServer('thing3', value=response_dict.get('field3', "0"))
            dev.updateStateOnServer('thing4', value=response_dict.get('field4', "0"))
            dev.updateStateOnServer('thing5', value=response_dict.get('field5', "0"))
            dev.updateStateOnServer('thing6', value=response_dict.get('field6', "0"))
            dev.updateStateOnServer('thing7', value=response_dict.get('field7', "0"))
            dev.updateStateOnServer('thing8', value=response_dict.get('field8', "0"))

            # Convert UTC return to local time. There is an optional timezone parameter that can be used in the form of: time_zone="timezone=America%2FChicago&"
            # For now, we will convert to UTC locally.
            if response_dict['created_at']:
                time = t.time()

                # time_delta_to_utc formula thanks to Karl (kw123).
                time_delta_to_utc = (int(t.mktime(dt.datetime.utcfromtimestamp(time + 10).timetuple()) - time) / 100) * 100
                utc_obj           = dt.datetime.strptime(response_dict['created_at'], '%Y-%m-%dT%H:%M:%SZ')
                local_time        = str(utc_obj - dt.timedelta(seconds=time_delta_to_utc))
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
        The following eight methods produce lists of states that are associated
        with user-selected devices when configuring Thingspeak reporting
        devices. Each list includes only states for the selected device.
        """

        self.debugLog(u'devStateGenerator1() method called.')

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
        """ See Docstring for devStateGenerator1 """

        self.debugLog(u"devStateGenerator2() called.")

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
        """ See Docstring for devStateGenerator1 """

        self.debugLog(u"devStateGenerator3() method called.")

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
        """ See Docstring for devStateGenerator1 """

        self.debugLog(u"devStateGenerator4() method called.")

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
        """ See Docstring for devStateGenerator1 """

        self.debugLog(u"devStateGenerator5() method called.")

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
        """ See Docstring for devStateGenerator1 """

        self.debugLog(u"devStateGenerator6() method called.")

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
        """ See Docstring for devStateGenerator1 """

        self.debugLog(u"devStateGenerator7() method called.")

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
        """ See Docstring for devStateGenerator1 """

        self.debugLog(u"devStateGenerator8() method called.")

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

    def devUnkillAllComms(self):
        """ devUnkillAllComms() sets the enabled status of all plugin devices
        to true. """

        self.debugLog(u"devUnkillAllComms() called.")

        for dev in indigo.devices.itervalues("self"):
            indigo.device.enable(dev, value=True)

    def encodeValueDicts(self):
        """ The encodeValueDicts() method is called when a device makes a call
        to upload data to Thingspeak. """

        # self.debugLog(u"encodeValueDicts() method called.")  # This is commented because it will print to the log every 2 seconds.

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
                last_update = dev.states['created_at']
                if last_update == '':
                    last_update = '1970-01-01 00:00:00'
                last_update = dt.datetime.strptime(last_update, '%Y-%m-%d %H:%M:%S')

                delta = dt.datetime.now() - last_update
                delta = int(delta.total_seconds())

                if delta > int(dev.pluginProps['devUploadInterval']):
                    dev.updateStateOnServer('thingState', value=False, uiValue="processing")

                    channel_id = dev.pluginProps['channelList']

                    # Get the write key for this channel
                    url = "/channels.json"
                    parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

                    response, response_dict = self.sendToThingspeak('get', url, parms)

                    # Find the write api key for this channel (we go and get it in case it's changed.
                    for thing in response_dict:
                        if str(thing['id']) == str(channel_id):
                            for key in thing['api_keys']:
                                if key['write_flag']:
                                    api_key = key['api_key']

                    if not api_key:
                        return

                    for v in range(8):
                        v += 1
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

                            self.debugLog(u" " * 22)
                            self.debugLog(unicode(u"ID: {0}".format(thing_1)))
                            self.debugLog(unicode(u"Item: {0}".format(state_1)))

                            # If it's a device state, do this:
                            if int(thing_1) in indigo.devices:

                                try:
                                    var = indigo.devices[int(thing_1)].states[state_1]
                                    var = self.onlyNumerics(var)
                                    self.debugLog(u"Value: {0}".format(var))

                                except ValueError:
                                    self.errorLog(u"{0} - {1} is non-numeric or has been removed. Will try to upload, but it won't chart.".format(dev.name, dev.pluginProps[thing_str]))
                                    var = u"undefined"
                                # Add device state value to dictionary.
                                thing_dict['field' + str(v)] = var

                            # If it's a variable value, do this:
                            elif int(thing_1) in indigo.variables:
                                var = indigo.variables[int(thing_1)].value

                                try:
                                    var = self.onlyNumerics(var)
                                    self.debugLog(u"Value: {0}".format(var))

                                except ValueError:
                                    self.errorLog(u"{0} - {1} is non-numeric or has been removed. Will try to upload, but it won't chart.".format(dev.name, dev.pluginProps[thing_str]))

                                # Add variable value to dictionary.
                                thing_dict['field' + str(v)] = var

                        thing_dict['elevation']  = self.pluginPrefs['elevation']
                        thing_dict['latitude']   = self.pluginPrefs['latitude']
                        thing_dict['longitude']  = self.pluginPrefs['longitude']
                        thing_dict['twitter']    = self.pluginPrefs['twitter']
                        thing_dict['tweet']      = u"{0}".format(dev.pluginProps['tweet'])

                    if self.debugLevel >= 2:
                        self.debugLog(unicode(thing_dict))

                    # Open a connection and upload data to Thingspeak
                    try:

                        # The plugin uploads variable values before moving on to the next one. Will continue until no more devices or the plugin throws an exception.
                        self.debugLog(u"{0}: Channel updating...".format(dev.name))
                        self.devPrepareForThingspeak(dev, thing_dict)

                    except Exception as error:

                        f = open(self.logFile, 'a')
                        f.write("{0} - Curl Return Code: {1}".format(dt.datetime.time(dt.datetime.now()), error))
                        f.close()

                        self.errorLog(unicode(error))
                else:
                    continue
        return

    def listGenerator(self, filter="", valuesDict=None, typeId="", targetId=0):
        """ The listGenerator() method returns the current list of devices and
        variables from the list 'self.devicesAndVariablesList'. """

        self.debugLog(u'listGenerator() called.')

        return self.devicesAndVariablesList

    def onlyNumerics(self, val):
        """
        This method evaluates values intended for upload. It ensures that the
        values are numeric only (i.e., stripping °F) and converting binary
        strings to integers. It also converts Indigo string values to floats
        as necessary.
        """

        self.debugLog(u"onlyNumerics() called.")

        try:
            # Does it float? Yes? Then it must be a witch.
            return float(val)

        # If it doesn't float, let's see if it's a string of a number, otherwise let's try to convert it t a boolean.
        except ValueError:
            val = val.upper()
            xx = ''.join([c for c in val if c in '1234567890.'])

            if len(xx) != 0:
                return xx

        if val in ("TRUE", "ON"):
            return 1

        if val in ("FALSE", "OFF"):
            return 0

    def sendToThingspeak(self, request_type, url, parms):
        """ The sendToThingspeak() method is
        called by several methods when data needs to be uploaded or downloaded.
        It returns a response code and a json dict (or returns an empty dict
        if no json is received from Thingspeak. """

        self.debugLog(u"sendToThingspeak() called.")

        response = ""
        response_dict = {}
        response_code = 0

        if self.debugLevel >= 3:
            self.debugLog(u"Warning! Debug set to high. Debug output contains your API keys.")
        else:
            self.debugLog(u"URL debug logging suppressed. Set debug level to high to write it to the log.")

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

            self.debugLog(url)

            try:
                response_dict = response.json()
            except:
                response_dict = {}

            response_code = response.status_code

            self.debugLog(u"Result: {0}".format(response_dict))

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

                indigo.server.log(response_error_msg_dict.get(response.status_code, u"Error unknown."))
                return response_code, response_dict

        except requests.exceptions.ConnectionError:
            self.errorLog(u"Unable to reach host. Will continue to attempt connection.")
            return response_code, response_dict

        except requests.exceptions.Timeout:
            self.errorLog(u"Host server timeout. Will continue to retry.")
            return response_code, response_dict

    def toggleDebug(self):
        """Toggle debug on/off."""

        self.debugLog(u"toggleDebug() called.")
        if not self.debug:
            self.debug = True
            self.pluginPrefs['showDebugInfo'] = True
            indigo.server.log(u"Debugging on.")
            self.debugLog(u"Debug level: {0}".format(self.debugLevel))
            if self.debugLevel >= 3:
                self.debugLog(u"Warning! Debug set to high. Sensitive information will be sent to the Indigo log.")

        else:
            self.debug = False
            self.pluginPrefs['showDebugInfo'] = False
            indigo.server.log(u"Debugging off.")

    def updateMenuConfigUi(self, valuesDict, menuId):
        """"""
        self.debugLog(u"updateMenuConfigUi() called.")

        if menuId == 'channelUpdate':
            url = "/channels.json"
            parms = {'api_key': self.pluginPrefs.get('apiKey', '')}

            response, response_dict = self.sendToThingspeak('get', url, parms)

            write_key = ""
            for thing in response_dict:
                if thing['id'] == int(valuesDict['channelList']):
                    valuesDict['description'] = thing['description']
                    valuesDict['metadata'] = thing['metadata']
                    valuesDict['name'] = thing['name']
                    valuesDict['tags'] = ",".join([tag['name'] for tag in thing['tags']])
                    valuesDict['url'] = thing['url']
                    valuesDict['public_flag'] = thing['public_flag']

                    self.debugLog(u"Channel Info: {0}".format(thing))
                    write_key = thing['api_keys'][0]['api_key']

            url = "/channels/{0}/feeds.json".format(int(valuesDict['channelList']))
            parms = {'api_key': write_key}

            response, response_dict = self.sendToThingspeak('get', url, parms)

            valuesDict['field1'] = response_dict['channel'].get('field1', '')
            valuesDict['field2'] = response_dict['channel'].get('field2', '')
            valuesDict['field3'] = response_dict['channel'].get('field3', '')
            valuesDict['field4'] = response_dict['channel'].get('field4', '')
            valuesDict['field5'] = response_dict['channel'].get('field5', '')
            valuesDict['field6'] = response_dict['channel'].get('field6', '')
            valuesDict['field7'] = response_dict['channel'].get('field7', '')
            valuesDict['field8'] = response_dict['channel'].get('field8', '')

        return valuesDict

    def updateThingspeakDataAction(self, valuesDict):
        """
        The updateThingspeakDataAction () method invokes an instantaneous
        update of the Thingspeak data channels. If this is called before 15
        seconds have elapsed since the last update, Thingspeak will ignore it.
        Unsure if the 15 second limit starts over.
        """

        self.debugLog(u"updateThingspeakDataAction() called.")
        self.encodeValueDicts()
        return

    def updateThingspeakDataMenu(self):
        """
        The updateThingspeakDataMenu() method invokes an instantaneous update
        of the Thingspeak data channels. If this is called before 15 seconds
        have elapsed since the last update, Thingspeak will ignore it. Unsure
        if the 15 second limit starts over.
        """

        self.debugLog(u"updateThingspeakDataMenu() called.")
        self.encodeValueDicts()
        return
