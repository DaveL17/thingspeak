#!/usr/bin/env python2.5
# -*- coding: utf-8 -*-

"""
Thingspeak Plugin
plugin.py
Author: DaveL17
Credits:    Chris - http://www.australianrobotics.com.au/news/how-to-
                    talk-to-thingspeak-with-python-a-memory-cpu-monitor
            Karl (kw123) - device state restriction methods
            Update Checker by: berkinet (with additional features by Travis Cook)

This script takes device and variable values and uploads them to
Thingspeak. In order to use it, you will need to have a Thingspeak
account, and have configured Thingspeak channels. Each Thingspeak
channel has a several API keys--this plugin uses an write key, which is
unique to each channel. To use the plugin, create individual Indigo
devices that represent a single Thingspeak channel. Under the device
configuration menu, enter the appropriate Thingspeak API key, and
assign Indigo devices or variables to each "Thing." Each plugin device
can hold up to eight variables (a Thingspeak limit, not the plugin's.
Currently, only numeric and binary variables will chart on Thingspeak,
and the plugin tries to adjust variable values as needed to make them
compatible (i.e., converting a string to a float.
"""

# TODO: Prettify debug output to Indigo log.
# TODO: Change kstateimagesel to .Error when that function is available.
# TODO: Update other plugins to take advantage of new
#       - sleep settings
#       - annotation of optional settings in plugins and manuals
# TODO: Twitter stuff?
# TODO: Status?
# TODO: Consider adding some additional device states like:
#       - if there was an error, etc.
# TODO: Provide a menu item to pull down information FROM Thingspeak??
#       - This is handled somewhat by logging the upload return. But there is
#         a potential need to download the entire data set and other information.
# TODO: Allow devices to control their own individual upload intervals (now a feature request) and also manual update (maybe hang a trigger on this?)
#       - This is non-trivial as the plugin would need to track mulitple
#         instances for multiple devices rather than a single sleep. One way
#         would be to set a "Next Data Upload" state for each device and
#         then poll the states every 'n' seconds.  Need to think more about
#         the best way to make this happen.
# TODO: refine status messages to Indigo UI when plugin is starting/stopping/refreshing.

import datetime
import os.path
import simplejson
import subprocess
import time
import urllib  # Use to encode the URL parameters.
import indigoPluginUpdateChecker

try:
    import indigo
except ImportError:
    pass

__author__    = "DaveL17"
__build__     = ""
__copyright__ = 'Copyright 2017 DaveL17'
__license__   = "MIT"
__title__     = 'Thingspeak Plugin for Indigo Home Control'
__version__   = '1.0.03'

kDefaultPluginPrefs = {
    u'configMenuTimeoutInterval': 15,            # How long to wait on a server timeout.
    u'configMenuUploadInterval' : 900,           # How long to wait before refreshing devices.
    u'elevation'                : 0,             # Elevation of data source.
    u'latitude'                 : 0,             # Latitude of data source.
    u'logFileDate'              : "1970-01-01",  # Log file creation date.
    u'longitude'                : 0,             # Longitude of data source.
    u'showDebugInfo'            : False,         # Verbose debug logging?
    u'showDebugLevel'           : 1,             # Low, Medium or High debug output.
    u'updaterEmail'             : "",            # Email to notify of plugin updates.
    u'updaterEmailsEnabled'     : False,         # Notification of plugin updates wanted.
    }

class Plugin(indigo.PluginBase):
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.debugLog(u"Thingspeak initialization called.")

        self.debug          = self.pluginPrefs.get('showDebugInfo', False)
        self.debugLevel     = self.pluginPrefs.get('showDebugLevel', 1)
        self.elevation      = self.pluginPrefs.get('elevation', 0)
        self.latitude       = self.pluginPrefs.get('latitude', 0)
        self.logFile        = '/Library/Application Support/Perceptive Automation/Indigo 6/Logs/Thingspeak Log.txt'
        self.logFileDate    = self.pluginPrefs.get('logFileDate', "1970-01-01")
        self.longitude      = self.pluginPrefs.get('longitude', 0)
        self.pluginName     = "com.fogbert.indigoplugin.thingspeak"
        self.uploadInterval = int(self.pluginPrefs.get('configMenuUploadInterval', 900))
        updater_url         = "https://davel17.github.io/thingspeak/thingspeak_version.html"
        self.updater        = indigoPluginUpdateChecker.updateChecker(self, updater_url)

        # Convert old debugLevel scale to new scale.
        # =============================================================
        if not 0 < self.pluginPrefs['showDebugLevel'] <= 3:
            if self.pluginPrefs['showDebugLevel'] == "High":
                self.pluginPrefs['showDebugLevel'] = 3
            elif self.pluginPrefs['showDebugLevel'] == "Medium":
                self.pluginPrefs['showDebugLevel'] = 2
            else:
                self.pluginPrefs['showDebugLevel'] = 1

        self.debugLevel = self.pluginPrefs.get('showDebugLevel', 1)

    def __del__(self):
        indigo.PluginBase.__del__(self)

    def startup(self):
        self.debugLog(u"Thingspeak startup() method called.")

        if self.debug and self.debugLevel >= 3:
            self.debugLog(u"Warning! Debug set to high. Sensitive information will be sent to the Indigo log.")

        self.updater.checkVersionPoll()  # See if there is an update and whether the user wants to be notified.

    def shutdown(self):
        self.debugLog(u"Thingspeak shutdown() method called.")  # Do any cleanup necessary before exiting
        """shutdown(self)"""

        for dev in indigo.devices.iter('self'):
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def deviceStartComm(self, dev):
        self.debugLog(u"deviceStartComm() method called. Starting Thingspeak device: {0}".format(dev.name))
        dev.stateListOrDisplayStateIdChanged()
        dev.updateStateOnServer('thingState', value=False, uiValue=u"Enabled")
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def deviceStopComm(self, dev):
        self.debugLog(u"deviceStopComm() method called. Stopping Thingspeak device: {0}".format(dev.name))
        dev.updateStateOnServer('thingState', value=False, uiValue=u"Disabled")

    def toggleDebugEnabled(self):
        # Toggle debug on/off.
        self.debugLog(u"toggleDebugEnabled() method called.")
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

    def validatePrefsConfigUi(self, valuesDict):
        self.debugLog(u"validatePrefsConfigUi() method called.")

        error_msg_dict = indigo.Dict()

        try:
            # Test elevation. Must be an integer (can not be a float. Can be negative.
            try:
                int(valuesDict['elevation'])
            except:
                error_msg_dict['elevation'] = (
                    u"Thingspeak requires elevation to be expressed as "
                    "a whole number integer. It can be positive or negative.")
                return False, valuesDict, error_msg_dict

            if "." in valuesDict['elevation']:
                error_msg_dict['elevation'] = (
                    u"Thingspeak requires elevation to be expressed as "
                    "a whole number integer. It can be positive or negative.")
                return False, valuesDict, error_msg_dict

            # Test latitude and longitude. Must be integers or floats. Can be negative.
            try:
                float(valuesDict['latitude'])
            except Exception as error:
                error_msg_dict['latitude'] = (
                    u"Thingspeak requires latitude to be expressed as "
                    "a whole number or decimal. It can be positive or negative.")
                return False, valuesDict, error_msg_dict

            try:
                float(valuesDict['longitude'])
            except Exception as error:
                error_msg_dict['longitude'] = (
                    u"Thingspeak requires longitude to be expressed as "
                    "a whole number or decimal. It can be positive or negative.")
                return False, valuesDict, error_msg_dict

            # Test plugin update notification settings.
            if valuesDict['updaterEmailsEnabled'] and not valuesDict['updaterEmail']:
                error_msg_dict['updaterEmail'] = (
                    u"If you want to be notified of updates, you must "
                    "supply an email address.")
                return False, valuesDict, error_msg_dict

            elif valuesDict['updaterEmailsEnabled'] and "@" not in valuesDict['updaterEmail']:
                error_msg_dict['updaterEmail'] = (
                    u"Valid email addresses have at least one @ symbol "
                    "in them (foo@bar.com).")
                return False, valuesDict, error_msg_dict

        except Exception as e:

            f = open(self.logFile, 'a')
            f.write("{0} - validatePrefsConfigUi error: {1}\n".format(datetime.datetime.time(datetime.datetime.now()), e))
            f.close()

            self.debugLog(u"Exception in validatePrefsConfigUi tests: {0}".format(e))
            pass

        return True, valuesDict

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        self.debugLog(u"closedPrefsConfigUi() method called.")

        if userCancelled:
            self.debugLog(u"User prefs dialog cancelled.")

        if not userCancelled:
            self.debug = valuesDict.get('showDebugInfo', False)
            self.debugLog(u"User prefs saved.")
            if self.pluginPrefs['showDebugLevel'] >= 3:
                self.debugLog(str(valuesDict))

            if self.debug:
                indigo.server.log(u"Debug logging is on.")
                if self.debugLevel >= 3:
                    self.debugLog(u"Warning! Debug set to high. Sensitive information will be sent to the Indigo log.")

        # Update update select globals if plugin prefs have changed.
        self.debugLevel     = self.pluginPrefs.get('showDebugLevel', 1)
        self.elevation      = self.pluginPrefs.get('elevation', 0)
        self.latitude       = self.pluginPrefs.get('latitude', 0)
        self.longitude      = self.pluginPrefs.get('longitude', 0)
        self.uploadInterval = int(self.pluginPrefs.get('configMenuUploadInterval', 900))

    def killAllComms(self):
        """ killAllComms() sets the enabled status of all plugin devices to
        false. """

        for dev in indigo.devices.itervalues("self"):
            try:
                indigo.device.enable(dev, value=False)
            except Exception as error:
                self.debugLog(u"Exception when trying to kill all comms. Error: {0}".format(error))

    def unkillAllComms(self):
        """ unkillAllComms() sets the enabled status of all plugin devices to
        true. """

        for dev in indigo.devices.itervalues("self"):
            try:
                indigo.device.enable(dev, value=True)
            except Exception as error:
                self.debugLog(u"Exception when trying to unkill all comms. Error: {0}".format(error))

    def checkDebugLogFile(self):
        """
        The checkDebugLogFile() method manages the Thingspeak Plugin
        logging facility. It ensures the log file always exists and
        that it never contains more than one day of logs.
        """
        self.debugLog(u"checkDebugLogFile() method called.")
        log     = datetime.datetime.strptime(self.pluginPrefs.get('logFileDate', "1970-01-01"), "%Y-%m-%d")
        log_date = datetime.datetime.date(log)
        now     = datetime.datetime.now()
        today   = datetime.datetime.date(now)

        # Create the log file if it doesn't exist or if it's a new day, delete the existing log file and create a new one.
        if not os.path.exists(self.logFile) or today > log_date:
            f = open(self.logFile, 'w')
            f.write(('*' * 72) + "\n")
            f.write("***{0}- Thingspeak Log - {1} - {2}***\n".format((' ' * 16), today, (' ' * 18)))
            f.write(('*' * 72) + "\n")
            f.close()

            self.pluginPrefs['logFileDate'] = str(today)  # Update plugin log date tracker with today's date.

    def checkVersionNow(self):
        self.debugLog(u"checkVersionNow() method called.")
        self.updater.checkVersionNow()

    def listGenerator(self, filter="", valuesDict=None, typeId="", targetId=0):
        """This method collects IDs and names for all Indigo devices and
        variables. It creates a list of the form:
        ((dev.id, dev.name), (var.id, var.name)).
        """
        self.debugLog(u"listGenerator() method called.")

        master_list = []
        [master_list.append((dev.id, u"(D) {0}".format(dev.name))) for dev in indigo.devices.iter()]
        [master_list.append((var.id, u"(V) {0}".format(var.name))) for var in indigo.variables.iter()]
        master_list.append(('None', 'None'))

        if self.debugLevel >= 3:
            self.debugLog(u"Generated list of devices and variables:")
            self.debugLog(unicode(master_list))

        return master_list

    def deviceStateGenerator1(self, filter="", valuesDict=None, typeId="", targetId=0):
        """
        The following eight methods produce lists of states that are
        associated with user-selected devices when configuring
        Thingspeak reporting devices. Each list includes only states
        for the selected device.
        """
        self.debugLog(u"deviceStateGenerator1 method called.")

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

    def deviceStateGenerator2(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.debugLog(u"deviceStateGenerator2 method called.")

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

    def deviceStateGenerator3(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.debugLog(u"deviceStateGenerator3 method called.")

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

    def deviceStateGenerator4(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.debugLog(u"deviceStateGenerator4 method called.")

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

    def deviceStateGenerator5(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.debugLog(u"deviceStateGenerator5 method called.")

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

    def deviceStateGenerator6(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.debugLog(u"deviceStateGenerator6 method called.")

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

    def deviceStateGenerator7(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.debugLog(u"deviceStateGenerator7 method called.")

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

    def deviceStateGenerator8(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.debugLog(u"deviceStateGenerator8 method called.")

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

        # Encode dicts of data for [type:Thingspeak] for upload.
        self.debugLog(u"encodeValueDicts() method called.")

        for dev in indigo.devices.itervalues("self"):

            # There are no Thingspeak devices yet.
            if not self.pluginName:
                self.debugLog(u"No Thingspeak devices have been created yet.")
                self.sleep(self.uploadInterval-5)

            # A device has been created, but hasn't been saved yet.
            elif not dev.configured:
                indigo.server.log(
                    u"A device is being (or has been) created, but "
                    "it's not fully configured. Sleeping while you finish.")
                self.sleep(self.uploadInterval-5)

            # A Thingspeak device has no API key.
            elif not (
                    dev.globalProps[self.pluginName]['apiKey'] or
                    dev.globalProps[self.pluginName]['apiKey'] == ""):

                indigo.server.log(u"Device {0} [{1}] has no API Key. Skipping device.".format(dev.name, dev.id))

            elif not dev.enabled:
                indigo.server.log(u"{0} device is disabled. Skipping.".format(dev.name))

            # Iterate over up to 8 values per device.
            elif dev.enabled:
                api_key    = dev.globalProps[self.pluginName]['apiKey']
                api_key    = self.fixApiKey(dev, api_key)
                thing_dict = {}

                for v in range(8):
                    v += 1
                    thing_str       = 'thing{0}'.format(v)
                    thing_state_str = 'thing{0}State'.format(v)

                    # Create the dict and add the API key to it.
                    thing_dict['key'] = api_key

                    # If there is a device created, but no value assigned.
                    if not dev.globalProps[self.pluginName][thing_str] or dev.globalProps[self.pluginName][thing_str] == "None":
                        var = "Null value"

                    else:
                        thing_1 = dev.globalProps[self.pluginName][thing_str]
                        state_1 = dev.globalProps[self.pluginName][thing_state_str]

                        self.debugLog(u" " * 22)
                        self.debugLog(unicode(u"ID: {0}".format(thing_1)))
                        self.debugLog(unicode(u"Item: {0}".format(state_1)))

                        # If it's a device state, do this:
                        if int(thing_1) in indigo.devices:

                            try:
                                var = indigo.devices[int(thing_1)].states[state_1]
                                var = self.onlyNumerics(var)
                                self.debugLog(u"Value: {0}".format(var))

                            except Exception as error:
                                self.errorLog(u"{0} - {1} is non-numeric or has been removed. "
                                              u"Will try to upload to Thingspeak, but it won't chart.".format(dev.name, dev.globalProps[self.pluginName][thing_str]))
                                var = u"undefined"
                            # Add device state value to dictionary.
                            thing_dict['field' + str(v)] = var

                        # If it's a variable value, do this:
                        elif int(thing_1) in indigo.variables:
                            var = indigo.variables[int(thing_1)].value

                            try:
                                var = self.onlyNumerics(var)
                                self.debugLog(u"Value: {0}".format(var))

                            except Exception as error:
                                self.errorLog(u"{0} - {1} is non-numeric or has been removed. "
                                              u"Will try to upload to Thingspeak, but it won't chart.".format(dev.name, dev.globalProps[self.pluginName][thing_str]))

                            # Add variable value to dictionary.
                            thing_dict['field' + str(v)] = var

                    thing_dict['elevation'] = self.elevation
                    thing_dict['latitude']  = self.latitude
                    thing_dict['longitude'] = self.longitude

                if self.debugLevel >= 2:
                    self.debugLog(unicode(thing_dict))

                # Open a connection and upload data to Thingspeak
                try:

                    params = urllib.urlencode(thing_dict)
                    self.debugLog(u"Channel updating...")

                    # The plugin uploads variable values before moving on to the next one. Will continue until no more devices or the plugin throws an exception.
                    self.uploadToThingspeak(dev, params)

                except Exception as e:

                    f = open(self.logFile, 'a')
                    f.write("{0} - Curl Return Code: {1}".format(datetime.datetime.time(datetime.datetime.now()), e))
                    f.close()

                    self.errorLog(str(e))

        return

    def fixApiKey(self, dev, api_key):
        """
        This method evaluates user-provided Thingspeak api WRITE keys
        for form and length. Where possible (and appropriate), it
        corrects common errors such as length, and leading/trailing
        spaces. It then writes the repaired api_key back to the
        device dict.
        """
        self.debugLog(u"fixApiKey() method called.")

        if api_key.startswith(" ") or api_key.endswith(" "):
            api_key = api_key.strip()
            self.errorLog(u"{0} API key includes leading and/or trailing spaces. Repairing.".format(dev.name))

            # Overwrite with repaired api_key as needed.
            new_props           = dev.pluginProps
            new_props['apiKey'] = api_key
            dev.replacePluginPropsOnServer(new_props)

        # Thingspeak keys are always 16 digits in length. Plugin will continue to run, but Thingspeak will reject/ignore (which?) the submission.
        if len(api_key) != 16:
            self.errorLog(u"API key value {0} for [{1}] is not the proper length. Check key.".format(api_key, dev.name))
        return api_key

    def onlyNumerics(self, seq):
        """
        This method evaluates values intended for upload. It ensures
        that the values are numeric only (i.e., stripping °F) and
        converting binary strings to integers. It also converts
        Indigo string values to floats as necessary.
        """
        self.debugLog(u"onlyNumerics() method called.")

        x = ""

        try:
            # Does it float? Yes? Then it must be a witch.
            x = float(seq)
            return x
        except Exception as error:
            xx = ''.join([c for c in seq if c in '1234567890.'])
            if len(''.join([c for c in xx if c in '1234567890'])) != 0:
                return xx
            seq = str(seq).upper()

        if seq.lower() or seq.upper() in ("TRUE", "ON"):
            x = 1

        if seq.lower or seq.upper() in ("FALSE", "OFF"):
            x = 0

        return x

    def stopSleep(self, start_sleep):
        """
        The stopSleep() method accounts for changes to the user
        upload interval preference. The plugin checks every 2 seconds
        to see if the sleep interval should be updated.
        """
        self.debugLog(u"stopSleep() method called.")
        try:
            # We subtract an additional 5 seconds to account for the 5 second sleep at the start of runConcurrentThread.
            total_sleep = float(self.pluginPrefs.get('configMenuUploadInterval', 900)) - 6
        except Exception as error:
            total_sleep = iTimer
        if time.time() - start_sleep > total_sleep:
            return True
        return False

    def updateThingspeakDataAction(self, valuesDict):
        """
        The updateThingspeakDataAction () method invokes an instantaneous
        update of the Thingspeak data channels. If this is called before
        15 seconds have elapsed since the last update, Thingspeak will
        ignore it. Unsure if the 15 second limit starts over.
        """
        self.debugLog(u"updateThingspeakDataAction() method called.")
        self.encodeValueDicts()
        return

    def updateThingspeakDataMenu(self):
        """
        The updateThingspeakDataMenu() method invokes an instantaneous
        update of the Thingspeak data channels. If this is called before
        15 seconds have elapsed since the last update, Thingspeak will
        ignore it. Unsure if the 15 second limit starts over.
        """
        self.debugLog(u"updateThingspeakDataMenu called.")
        self.encodeValueDicts()
        return

    def uploadToThingspeak(self, dev, params):
        """
        This method performs the upload to Thingspeak, evaluates, and
        logs the result.
        """
        self.debugLog(u"uploadToThingspeak() method called.")

        try:

            # Build upload URL.
            if dev.globalProps[self.pluginName]['devicePort']:
                ts_ip = dev.globalProps[self.pluginName]['deviceIP']
            else:
                ts_ip = "api.thingspeak.com"

            url = "https://{0}/update.json?{1}".format(ts_ip, params)
            if self.debugLevel >= 3:
                self.debugLog(u"Warning! Debug set to high. Upload URL containing your API key(s) written was written to debug output.")
                self.debugLog(url)
            else:
                self.debugLog(u"URL debug logging suppressed. Set debug level to high to write it to the log.")

            # Initiate curl call to Thingspeak servers.
            proc = subprocess.Popen(["curl", '-vs', url], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (result, err) = proc.communicate()

            # Process the results.
            # Thingspeak will respond with a "0" if they something went wrong.
            if len(result) > 0 and result != "0":

                result = simplejson.loads(result, encoding="utf-8")

                for key, value in result.iteritems():
                    if not value:
                        result[key] = "0"

                dev.updateStateOnServer('channel_id', value=int(result['channel_id']), uiValue=unicode(result['channel_id']))
                dev.updateStateOnServer('elevation', value=int(result['elevation']), uiValue=unicode(result['elevation']))
                dev.updateStateOnServer('entry_id', value=int(result['entry_id']), uiValue=unicode(result['entry_id']))
                dev.updateStateOnServer('latitude', value=float(result['latitude']), uiValue=unicode(result['latitude']))
                dev.updateStateOnServer('longitude', value=float(result['longitude']), uiValue=unicode(result['longitude']))
                dev.updateStateOnServer('status', value=result['status'], uiValue=result['status'])
                dev.updateStateOnServer('thing1', value=result['field1'], uiValue=result['field1'])
                dev.updateStateOnServer('thing2', value=result['field2'], uiValue=result['field2'])
                dev.updateStateOnServer('thing3', value=result['field3'], uiValue=result['field3'])
                dev.updateStateOnServer('thing4', value=result['field4'], uiValue=result['field4'])
                dev.updateStateOnServer('thing5', value=result['field5'], uiValue=result['field5'])
                dev.updateStateOnServer('thing6', value=result['field6'], uiValue=result['field6'])
                dev.updateStateOnServer('thing7', value=result['field7'], uiValue=result['field7'])
                dev.updateStateOnServer('thing8', value=result['field8'], uiValue=result['field8'])
#                 dev.updateStateOnServer('twitter', value=result['twitter'], uiValue=result['twitter'])
#                 dev.updateStateOnServer('tweet', value=result['tweet'], uiValue=result['tweet'])

                # Convert UTC return to local time. There is an optional timezone parameter that can be used in the form of: time_zone="timezone=America%2FChicago&"
                # For now, we will convert to UTC locally.
                if result['created_at']:
                    t   = time.time()
                    utc = result['created_at']

                    # time_delta_to_utc formula thanks to Karl (kw123).
                    time_delta_to_utc = (int(time.mktime(datetime.datetime.utcfromtimestamp(t + 10).timetuple()) - t) / 100) * 100
                    utc_obj           = datetime.datetime.strptime(utc, '%Y-%m-%dT%H:%M:%SZ')
                    local_time        = str(utc_obj - datetime.timedelta(seconds=time_delta_to_utc))
                    dev.updateStateOnServer('created_at', value=local_time, uiValue=local_time)
                else:
                    dev.updateStateOnServer('created_at', value=u"Unknown", uiValue=u"Unknown")

                dev.updateStateOnServer('thingState', value=True, uiValue=" ")
                dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                return

            # Something didn't go the way we wanted it to.
            if err:
                if proc.returncode == 6:

                    f = open(self.logFile, 'a')
                    f.write("{0} - uploadToThingSpeak()\nCurl Return Code: {1}\n{2} \n".format(datetime.datetime.time(datetime.datetime.now()), proc.returncode, err))
                    f.close()

                    self.errorLog(u"Error: Could not resolve host. Possible causes:")
                    self.errorLog(u"  The Thingspeak service is offline.")
                    self.errorLog(u"  Your Indigo server can not reach the Internet.")
                    self.errorLog(u"  Your plugin is mis-configured.")
                    self.debugLog(err)
                    dev.updateStateOnServer('thingState', value=False, uiValue="no comm")
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

                elif err != "":

                    f = open(self.logFile, 'a')
                    f.write("{0} - Curl Return Code: {1}\n {2} \n".format(datetime.datetime.time(datetime.datetime.now()), proc.returncode, err))
                    f.close()

                    self.debugLog(u"\n{0}".format(err))
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
                    dev.updateStateOnServer('thingState', value=False, uiValue="error")
                return

        # Something didn't go the way we wanted it to that we didn't anticipate.
        except Exception as e:

            f = open(self.logFile, 'a')
            f.write("{0} - Misc Exception: {1}\n".format(datetime.datetime.time(datetime.datetime.now()), e))
            f.close()

            self.errorLog(u"Unable to upload Thingspeak data. Reason: Exception - {0}".format(e))
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
            dev.updateStateOnServer('thingState', value=False, uiValue="error")
            pass

        return

    def runConcurrentThread(self):
        self.debugLog(u"runConcurrentThread initiated.")

        try:
            while True:
                self.sleep(5)
                self.updater.checkVersionPoll()
                self.checkDebugLogFile()
                self.encodeValueDicts()

                start_sleep = time.time()
                while True:
                    if self.stopSleep(start_sleep):
                        break
                    self.sleep(2)

        except self.StopThread:
            # Do any cleanup necessary before stopping
            self.debugLog(u"Thingspeak stop thread called.")
            pass
