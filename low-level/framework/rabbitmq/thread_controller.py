"""
 ****************************************************************************
 Filename:          thread_controller.py
 Description:       Provides the ability to manipulate running threads
                    within the framework.
 Creation Date:     02/02/2015
 Author:            Jake Abernathy

 Do NOT modify or remove this copyright and confidentiality notice!
 Copyright (c) 2001 - $Date: 2015/01/14 $ Seagate Technology, LLC.
 The code contained herein is CONFIDENTIAL to Seagate Technology, LLC.
 Portions are also trade secret. Any use, duplication, derivation, distribution
 or disclosure of this code, for any reason, not expressly authorized is
 prohibited. All other rights are expressly reserved by Seagate Technology, LLC.
 ****************************************************************************
"""

import os
import time
import json
from threading import Thread
from socket import gethostname

from framework.base.module_thread import ScheduledModuleThread
from framework.base.internal_msgQ import InternalMsgQ
from framework.utils.service_logging import logger

from json_msgs.messages.actuators.thread_controller import ThreadControllerMsg

# Import modules to control
from framework.rabbitmq.rabbitmq_egress_processor import RabbitMQegressProcessor
from framework.rabbitmq.rabbitmq_ingress_processor import RabbitMQingressProcessor
from framework.rabbitmq.plane_cntrl_rmq_egress_processor import PlaneCntrlRMQegressProcessor
from framework.rabbitmq.logging_processor import LoggingProcessor

# Note that all threaded message handlers must have an import here to be controlled
from message_handlers.logging_msg_handler import LoggingMsgHandler
from message_handlers.disk_msg_handler import DiskMsgHandler
from message_handlers.service_msg_handler import ServiceMsgHandler
from message_handlers.node_data_msg_handler import NodeDataMsgHandler
from message_handlers.node_controller_msg_handler import NodeControllerMsgHandler
from message_handlers.plane_cntrl_msg_handler import PlaneCntrlMsgHandler
from message_handlers.real_stor_encl_msg_handler import RealStorEnclMsgHandler


# Global method used by Thread to capture and log errors.  This must be global.
def _run_thread_capture_errors(curr_module, sspl_modules, msgQlist, conf_reader, products):
    """Run the given thread and log any errors that happen on it.
    Will stop all sspl_modules if one of them fails."""
    try:
        # Each module is passed a reference list to message queues so it can transmit
        #  internal messages to other modules as desired
        curr_module.initialize(conf_reader, msgQlist, products)
        curr_module.start()

    except BaseException as ex:
        logger.critical("SSPL-LL encountered a fatal error, terminating service Error: %s" % ex)
        logger.exception(ex)

        # Populate an actuator response message and transmit back to HAlon
        error_msg = "SSPL-LL encountered an error, terminating service Error: " + \
                    ", Exception: " + logger.exception(ex)
        jsonMsg   = ThreadControllerMsg(curr_module.name(), error_msg).getJson()

        for product in products:
            if product in ["CS-A", "EES"]:
                self._write_internal_msgQ(RabbitMQegressProcessor.name(), jsonMsg)
                break
            elif product == "CS-L" or \
               product == "CS-G":
                self._write_internal_msgQ(PlaneCntrlRMQegressProcessor.name(), jsonMsg)
                break

        # Shut it down, error is non-recoverable
        for name, other_module in sspl_modules.iteritems():
            if other_module is not curr_module:
                other_module.shutdown()


class ThreadController(ScheduledModuleThread, InternalMsgQ):

    MODULE_NAME = "ThreadController"
    PRIORITY    = 1

    # Section and keys in configuration file
    THREADCONTROLLER    = MODULE_NAME.upper()


    @staticmethod
    def name():
        """ @return: name of the monitoring module."""
        return ThreadController.MODULE_NAME

    def __init__(self):
        super(ThreadController, self).__init__(self.MODULE_NAME,
                                                  self.PRIORITY)
        self._threads_initialized = False
        self._thread_response     = "N/A"
        self.debug_section        = None

        # Location of hpi data directory populated by dcs-collector
        self._hpi_base_dir = "/tmp/dcs/hpi"
        self._start_delay  = 10
        self._systemd_support = True
        self._hostname = gethostname()

    def initialize(self, conf_reader, msgQlist, products):
        """initialize configuration reader and internal msg queues"""
        # Initialize ScheduledMonitorThread
        super(ThreadController, self).initialize(conf_reader)

        # Initialize internal message queues for this module
        super(ThreadController, self).initialize_msgQ(msgQlist)

    def initialize_thread_list(self, sspl_modules, operating_system, products, systemd_support):
        """initialize list of references to all modules"""
        self._sspl_modules     = sspl_modules
        self._products         = products
        self._operating_system = operating_system
        self._systemd_support  = systemd_support

        if operating_system == "centos7":
            # Note that all threaded sensors and actuators must have an import here to be controlled
            from sensors.impl.centos_7.systemd_watchdog import SystemdWatchdog
            from sensors.impl.centos_7.drive_manager import DriveManager
            from sensors.impl.centos_7.hpi_monitor import HPIMonitor

        # Handle configurations for specific products
        for product in self._products:
            if product in ["CS-A", "EES"]:
                from sensors.impl.generic.raid import RAIDsensor
                from sensors.impl.generic.SMR_drive_data import SMRdriveData

                # TODO: add this in product=EES check
                from sensors.impl.platforms.realstor.realstor_disk_sensor \
                import RealStorDiskSensor

                from sensors.impl.generic.psu_sensor import RealStorPSUSensor
                from sensors.impl.generic.realstor_fan_sensor import RealStorFanSensor
                from sensors.impl.generic.realstor_controller_sensor import RealStorControllerSensor
                break

    def run(self):
        """Run the module periodically on its own thread."""
        for product in self._products:
            if product in ["CS-A", "EES"] and \
               not self._threads_initialized:

                # Disabling for EES-non-requitement
                # Removing the code which waits for /tmp/dcs/hpi directory to get populated

                # Allow other threads to initialize
                time.sleep(185)

                # Notify external applications that've started up successfully
                startup_msg = "SSPL-LL service has started successfully"
                jsonMsg     = ThreadControllerMsg(ThreadController.name(), startup_msg).getJson()
                self._write_internal_msgQ(RabbitMQegressProcessor.name(), jsonMsg)
                self._threads_initialized = True

                # Let systemd know that we've started up successfully and ready for it to monitor sspl
                if self._systemd_support:
                    from systemd.daemon import notify
                    notify("READY=1")

                #self._set_debug(True)
                #self._set_debug_persist(True)
                self._log_debug("Start accepting requests")
        try:
            # Block on message queue until it contains an entry
            jsonMsg = self._read_my_msgQ()

            if jsonMsg is not None:
                self._process_msg(jsonMsg)

            # Keep processing until the message queue is empty
            while not self._is_my_msgQ_empty():
                jsonMsg = self._read_my_msgQ()
                if jsonMsg is not None:
                    self._process_msg(jsonMsg)

        except Exception as ex:
            # Log it and restart the whole process when a failure occurs
            logger.exception("ThreadController restarting: %r" % ex)

        self._scheduler.enter(1, self._priority, self.run, ())
        self._log_debug("Finished processing successfully")

    def _process_msg(self, jsonMsg):
        """Parses the incoming message and calls the appropriate method"""
        self._log_debug("_process_msg, jsonMsg: %s" % jsonMsg)

        # Check to see if debug mode is being globally turned off on all modules
        if self._check_reset_all_modules(jsonMsg) == True:
            return

        # Parse out the module name and request
        module_name    = jsonMsg.get("actuator_request_type").get("thread_controller").get("module_name")
        thread_request = jsonMsg.get("actuator_request_type").get("thread_controller").get("thread_request")

        # Parse out the uuid so that it can be sent back in Ack message
        uuid = None
        if jsonMsg.get("sspl_ll_msg_header") is not None and \
           jsonMsg.get("sspl_ll_msg_header").get("uuid") is not None:
            uuid = jsonMsg.get("sspl_ll_msg_header").get("uuid")
            self._log_debug("_processMsg, uuid: %s" % uuid)

        # Pass along the debug section to the module
        if jsonMsg.get("sspl_ll_debug") is not None:
            self.debug_section = { "sspl_ll_debug": {}}
            self.debug_section["sspl_ll_debug"] = jsonMsg.get("sspl_ll_debug")
        else:
            self.debug_section = None

        self._log_debug("_process_msg, self.debug_section: %s" % self.debug_section)

        # Parse out thread request and call the appropriate method
        if thread_request == "restart":
            self._restart_module(module_name)
        elif thread_request == "start":
            self._start_module(module_name)
        elif thread_request == "stop":
            # Don't let the outside world stop us from using RabbitMQ connection or shut down this thread
            if module_name == "RabbitMQegressProcessor" or \
                module_name == "RabbitMQingressProcessor" or \
                module_name == "ThreadController":
                    logger.warn("Attempt to stop RabbitMQ or ThreadController Processors, \
                                    ignoring. Please try 'restart' instead.")
                    return
            self._stop_module(module_name)
        elif thread_request == "status":
            self._status_module(module_name)
        else:
            self._thread_response = "Error, unrecognized thread request"

        node_id = []
        if jsonMsg.get("actuator_request_type").get("thread_controller").get("parameters") is not None and \
           jsonMsg.get("actuator_request_type").get("thread_controller").get("parameters").get("node_id"):
            node_id = jsonMsg.get("actuator_request_type").get("thread_controller").get("parameters").get("node_id")

        ack_type = {}
        ack_type["hostname"] = unicode(self._hostname, 'utf-8')
        ack_type["node_id"]  = node_id

        # Populate an actuator response message and transmit
        threadControllerMsg = ThreadControllerMsg(module_name, self._thread_response, \
                                                  json.dumps(ack_type))

        if uuid is not None:
            threadControllerMsg.set_uuid(uuid)
        msgString = threadControllerMsg.getJson()
        logger.info("ThreadController, response: %s" % str(msgString))
        for product in self._products:
            if product in ["CS-A", "EES"]:
                self._write_internal_msgQ(RabbitMQegressProcessor.name(), msgString)
                break
            elif product == "CS-L" or \
                 product == "CS-G":
                self._write_internal_msgQ(PlaneCntrlRMQegressProcessor.name(), msgString)
                break

    def _restart_module(self, module_name):
        """Restart a module"""
        self._log_debug("_restart_module, module_name: %s" % module_name)

        try:
            # Stop the module if it's running and let existing thread die gracefully
            if self._status_module(module_name) == True:
                self._stop_module(module_name)

            # Allow module a few seconds to shut down gracefully
            max_wait  = 10
            curr_wait = 1
            while self._status_module(module_name) == True:
                time.sleep(3)
                logger.info("Retrying: %s" % str(curr_wait))
                self._stop_module(module_name)
                curr_wait += 1
                if curr_wait > max_wait:
                    break

            # Start the module
            self._start_module(module_name)
        except Exception as ae:
            logger.warn("Restart thread failed: %s" % str(ae))
            self._thread_response = "Restart Failed"
        else:
            self._thread_response = "Restart Successful"

    def _stop_module(self, module_name):
        """Stop a module"""
        self._log_debug("_stop_module, module_name: %s" % module_name)

        try:
            if self._status_module(module_name) == False:
                self._log_debug("_stop_module, status: False")
                return

            self._thread_response = "Stop Successful"

            # Put a debug message on the module's queue before shutting it down
            if self.debug_section is not None:
                self._write_internal_msgQ(module_name, self.debug_section)

            # Call the module's shutdown method for a graceful halt
            self._sspl_modules[module_name].shutdown()
        except Exception as ae:
            logger.warn("Stop thread failed: %s" % str(ae))
            self._thread_response = "Stop Failed"

    def _start_module(self, module_name):
        """Start a module"""
        self._log_debug("_start_module, module_name: %s" % module_name)

        try:
            if self._status_module(module_name) == True:
                self._log_debug("_start_module, status: True")
                return

            self._thread_response = "Start Successful"

            module_thread = Thread(target=_run_thread_capture_errors,
                                      args=(self._sspl_modules[module_name], self._sspl_modules,
                                      self._msgQlist, self._conf_reader, self._products))

            # Put a configure debug message on the module's queue before starting it up
            if self.debug_section is not None:
                self._write_internal_msgQ(module_name, self.debug_section)

            module_thread.start()
        except Exception as ae:
            logger.warn("Start thread failed: %s" % str(ae))
            self._thread_response = "Start Failed"

    def _status_module(self, module_name):
        """Returns if the module is running or not"""
        if self._sspl_modules[module_name].is_running() == True:
            self._thread_response = "Status: Running"
        else:
            self._thread_response = "Status: Halted"

        self._log_debug("_status_module, module_name: %s, _thread_response: %s" %
                        (module_name, self._thread_response))
        return self._sspl_modules[module_name].is_running()

    def _check_reset_all_modules(self, jsonMsg):
        """Restarts all modules with debug mode off. Activated by internal_msgQ"""
        if jsonMsg.get("sspl_ll_debug") is not None and \
            jsonMsg.get("sspl_ll_debug").get("debug_component") is not None and \
            jsonMsg.get("sspl_ll_debug").get("debug_component") == "all":
                for module in self._sspl_modules:
                    self._log_debug("_check_reset_all_modules, module: %s" % module)
                    # Don't restart this thread or it won't complete the loop
                    if module != self.name():
                        self._restart_module(module)

                # Populate an actuator response message and transmit
                msgString = ThreadControllerMsg("All Modules", "Restarted with debug mode off").getJson()
                self._write_internal_msgQ(RabbitMQegressProcessor.name(), msgString)
                return True

        return False

    def shutdown_all_modules(self):
        """Calls shutdown for all modules"""
        logger.info("Shutting down all modules")
        for name, other_module in self._sspl_modules.iteritems():
            other_module.shutdown()

    def shutdown(self):
        """Clean up scheduler queue and gracefully shutdown thread"""
        super(ThreadController, self).shutdown()

    def check_RabbitMQegressProcessor_is_running(self):
        """Used by the shutdown_handler to allow queued egress msgs to complete"""
        for product in self._products:
            if product in ["CS-A", "EES"]:
                return self._sspl_modules[PlaneCntrlRMQegressProcessor.name()].is_running()
            elif product == "CS-L" or \
                 product == "CS-G":
                return self._sspl_modules[RabbitMQegressProcessor.name()].is_running()
