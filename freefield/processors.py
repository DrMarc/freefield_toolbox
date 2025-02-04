from sys import platform
import numpy as np
from freefield import DIR
import os.path
import random
import logging
from typing import Union
from collections import Counter
try:
    import win32com.client
except ModuleNotFoundError:
    win32com = None
    logging.warning('Could not import pywin32 - working with TDT devices is disabled')


class Processors(object):
    """
    Class for handling initialization of and basic input/output to TDT-processors.
    Methods include: initializing processors, writing and reading data, sending
    triggers and halting the processors.
    """

    def __init__(self):
        self.procs = dict()
        self.mode = None
        self._zbus = None

    def initialize(self, proc_list, zbus=False, connection='GB'):
        """
        Establish connection to one or several TDT-processors.

        Initialize the processors listed in proc_list, which can be a list
        or list of lists. The list / each sublist contains the name and model
        of a processor as well as the path to an rcx-file with the circuit that is
        run on the processor. Elements must be in order name - model - circuit.
        If zbus is True, initialize the ZBus-interface. If the processors are
        already initialized they are reset

        Args:
            proc_list : each sub-list represents one
                processor. Contains name, model and circuit in that order
            zbus : if True, initialize the Zbus interface.
            connection: type of connection to processor, can be "GB" (optical) or "USB"

        Examples:
        #    >>> devs = Processors()
        #    >>> # initialize a processor of model 'RP2', named 'RP2' and load
        #    >>> # the circuit 'example.rcx'. Also initialize ZBus interface:
        #    >>> devs.initialize_processors(['RP2', 'RP2', 'example.rcx'], True)
        #    >>> # initialize two processors of model 'RX8' named 'RX81' and 'RX82'
        #    >>>devs.initialize_processors(['RX81', 'RX8', 'example.rcx'],
        #    >>>                        ['RX82', 'RX8', 'example.rcx'])
        """
        # TODO: check if names are unique and id rcx files do exist
        logging.info('Initializing TDT processors, this may take a moment ...')
        models = []
        if not all([isinstance(p, list) for p in proc_list]):
            proc_list = [proc_list]  # if a single list was provided, wrap it in another list
        for name, model, circuit in proc_list:
            # advance index if a model appears more then once
            models.append(model)
            index = Counter(models)[model]
            print(f"initializing {name} of type {model} with index {index}")
            self.procs[name] = self._initialize_proc(model, circuit,
                                                     connection, index)
        if zbus:
            self._zbus = self._initialize_zbus(connection)
        if self.mode is None:
            self.mode = "custom"

    def initialize_default(self, mode: str) -> None:
        """
        Initialize processors in a default configuration.

        This function provides a convenient wrapper for initialize_processors.
        depending on the mode, processor names and models and rcx files are chosen
        and initialize_processors is called. The modes cover the core functions
        of the toolbox and include:

        'play_rec': play sounds using two RX8s and record them with a RP2
        'play_birec': same as 'play_rec' but record from 2 microphone channels
        'loctest_freefield': sound localization test under freefield conditions
        'loctest_headphones': localization test with headphones
        'cam_calibration': calibrate cameras for headpose estimation

        Args:
            mode (str): default configuration for initializing processors
        """
        if mode.lower() == 'play_rec':
            proc_list = [['RP2', 'RP2',  DIR/'data'/'rcx'/'rec_buf.rcx'],
                         ['RX81', 'RX8', DIR/'data'/'rcx'/'play_buf.rcx'],
                         ['RX82', 'RX8', DIR/'data'/'rcx'/'play_buf.rcx']]
        elif mode.lower() == "play_birec":
            proc_list = [['RP2', 'RP2',  DIR/'data'/'rcx'/'bi_rec_buf.rcx'],
                         ['RX81', 'RX8', DIR/'data'/'rcx'/'play_buf.rcx'],
                         ['RX82', 'RX8', DIR/'data'/'rcx'/'play_buf.rcx']]
        elif mode.lower() == "loctest_freefield":
            proc_list = [['RP2', 'RP2',  DIR/'data'/'rcx'/'button.rcx'],
                         ['RX81', 'RX8', DIR/'data'/'rcx'/'play_buf.rcx'],
                         ['RX82', 'RX8', DIR/'data'/'rcx'/'play_buf.rcx']]
        elif mode.lower() == "loctest_headphones":
            proc_list = [['RP2', 'RP2',  DIR/'data'/'rcx'/'bi_play_buf.rcx'],
                         ['RX81', 'RX8', DIR/'data'/'rcx'/'bits.rcx'],
                         ['RX82', 'RX8', DIR/'data'/'rcx'/'bits.rcx']]
        elif mode.lower() == "cam_calibration":
            proc_list = [['RP2', 'RP2',  DIR/'data'/'rcx'/'button.rcx'],
                           ['RX81', 'RX8', DIR/'data'/'rcx'/'bits.rcx'],
                           ['RX82', 'RX8', DIR/'data'/'rcx'/'bits.rcx']]
        else:
            raise ValueError(f'mode {mode} is not a valid input!')
        self.mode = mode
        logging.info(f'set mode to {mode}')
        self.initialize(proc_list, True, "GB")

    def write(self, tag, value, procs) :
        """
        Write data to processor(s).

        Set a tag on one or multiple processors to a given value. Processors
        are addressed by their name (the key in the _procs dictionary). The same
        tag can be set to the same value on multiple processors by passing a
        list of names.

        This function will call SetTagVal or WriteTagV depending on whether
        value is a single integer or float or an array. If the tag could
        not be set (there are different reasons why that might be the case) a
        warning is triggered. CAUTION: If the data type of the value arg does
        not match the data type of the tag, write might be successful but
        the processor might behave strangely.

        Args:
            tag : name of the tag in the rcx-circuit where value is
                written to
            value : value that is written to the tag. Must
                match the data type of the tag.
            procs : name(s) of the processor(s) to write to
        Examples:
        #    >>> # set the value of tag 'data' on RX81 & RX82 to 0
        #    >>> write('data', 0, ['RX81', 'RX82'])
        """
        if isinstance(value, (np.int32, np.int64)):
            value = int(value)  # use built-int data type
        if isinstance(procs, str):
            if procs == "RX8s":
                procs = [proc for proc in self.procs.keys() if "RX8" in proc]
            elif procs == "all":
                procs = list(self.procs.keys())
            else:
                procs = [procs]
        # Check if the procs are actually there
        if not set(procs).issubset(self.procs.keys()):
            raise ValueError('Can not find some of the specified processors!')
        flag = 0
        for proc in procs:
            if isinstance(value, (list, np.ndarray)):  # TODO: fix this
                value = np.array(value)  # convert to array
                if value.ndim > 1:
                    value = value.flatten()
                flag = self.procs[proc]._oleobj_.InvokeTypes(
                    15, 0x0, 1, (3, 0), ((8, 0), (3, 0), (0x2005, 0)),
                    tag, 0, value)
                logging.info(f'Set {tag} on {proc}.')
            else:
                flag = self.procs[proc].SetTagVal(tag, value)
                logging.info(f'Set {tag} to {value} on {proc}.')
            if flag == 0:
                logging.warning(f'Unable to set tag {tag} on {proc}')
        return flag

    def read(self, tag, proc, n_samples=1):
        """
        Read data from processor.

        Get the value of a tag from a processor. The number of samples to read
        must be specified, default is 1 which means reading a single float or
        integer value. Unlike in the write method, reading multiple variables
        in one call of the function is not supported.

        Args:
            tag: name of the processor to write to
            proc: processor to read from
            n_samples: number of samples to read from processor, default=1
        Returns:
            type (int, float, list): value read from the tag
        """
        if n_samples > 1:
            value = np.asarray(self.procs[proc].ReadTagV(tag, 0, n_samples))
        else:
            value = self.procs[proc].GetTagVal(tag)
        logging.info(f'Got {tag} from {proc}.')
        return value

    def halt(self):
        """
        Halt all currently active processors.
        """
        # TODO: can we see if halting was successfull
        for proc_name in self.procs.keys():
            proc = self.procs[proc_name]
            if hasattr(proc, 'Halt'):
                logging.info(f'Halting {proc_name}.')
                proc.Halt()

    def trigger(self, kind='zBusA', proc=None):
        """
        Send a trigger to the processors.

        Use software or the zBus-interface (must be initialized) to send
        a trigger to processors. The zBus triggers are send to
        all processors by definition. For the software triggers, once has to
        specify the processor(s).

        Args:
            kind (str, int): kind of trigger that is send. For zBus triggers
                this can be 'zBusA' or 'zBusB', for software triggers it can
                be any integer.
            proc: processor to trigger - only necessary when using software triggers
        """
        if isinstance(kind, (int, float)):
            if not proc:
                raise ValueError('Proc needs to be specified for SoftTrig!')
            self.procs[proc].SoftTrg(kind)
            logging.info(f'SoftTrig {kind} sent to {proc}.')
        elif 'zbus' in kind.lower():
            if self._zbus is None:
                raise ValueError('ZBus needs to be initialized first!')
            elif kind.lower() == "zbusa":
                self._zbus.zBusTrigA(0, 0, 20)
                logging.info('zBusA trigger sent.')
            elif kind.lower() == "zbusb":
                self._zbus.zBusTrigB(0, 0, 20)
        else:
            raise ValueError("Unknown trigger type! Must be 'soft', "
                             "'zBusA' or 'zBusB'!")

    @staticmethod
    def _initialize_proc(model: str, circuit: str, connection: str, index: int):
        if win32com is not None:
            try:
                rp = win32com.client.Dispatch('RPco.X')
            except win32com.client.pythoncom.com_error as err:
                raise ValueError(err)
        else:
            rp = _COM()
        logging.info(f'Connecting to {model} processor ...')
        connected = 0
        if model.upper() == 'RP2':
            connected = rp.ConnectRP2(connection, index)
        elif model.upper() == 'RX8':
            connected = rp.ConnectRX8(connection, index)
        elif model.upper() == 'RM1':
            connected = rp.ConnectRX8(connection, index)
        elif model.upper() == 'RX6':
            connected = rp.ConnectRX8(connection, index)
        if not connected:
            logging.warning(f'Unable to connect to {model} processor!')
        else:  # connecting was successful, load circuit
            if not rp.ClearCOF():
                logging.warning('clearing control object file failed')
            if not rp.LoadCOF(circuit):
                logging.warning(f'could not load {circuit}.')
            else:
                logging.info(f'{circuit} loaded!')
            if not rp.Run():
                logging.warning(f'Failed to run {model} processor')
            else:
                logging.info(f'{model} processor is running...')
            return rp

    @staticmethod
    def _initialize_zbus(connection: str = "GB"):
        zb = _COM()
        if win32com is not None:
            try:
                zb = win32com.client.Dispatch('ZBUS.x')
            except win32com.client.pythoncom.com_error as err:
                logging.warning(err)
        if zb.ConnectZBUS(connection):
            logging.info('Connected to ZBUS.')
        else:
            logging.warning('Failed to connect to ZBUS.')
        return zb


class _COM:
    """
    Working with TDT processors is only possible on windows machines. This dummy class
    simulates the output of a processor to test code on other operating systems
    """
    @staticmethod
    def ConnectRX8(connection: str, index: int) -> int:
        if connection not in ["GB", "USB"]:
            return 0
        if not isinstance(index, int):
            return 0
        else:
            return 1

    @staticmethod
    def ConnectRP2(connection: str, index: int) -> int:
        if connection not in ["GB", "USB"]:
            return 0
        if not isinstance(index, int):
            return 0
        else:
            return 1

    @staticmethod
    def ConnectRM1(connection: str, index: int) -> int:
        if connection not in ["GB", "USB"]:
            return 0
        if not isinstance(index, int):
            return 0
        else:
            return 1

    @staticmethod
    def ConnectRX6(connection: str, index: int) -> int:
        if connection not in ["GB", "USB"]:
            return 0
        if not isinstance(index, int):
            return 0
        else:
            return 1

    @staticmethod
    def ClearCOF() -> int:
        return 1

    @staticmethod
    def LoadCOF(circuit: str) -> int:
        if not os.path.isfile(circuit):
            return 0
        else:
            return 1

    @staticmethod
    def Run() -> int:
        return 1

    @staticmethod
    def ConnectZBUS(connection: str) -> int:
        if connection not in ["GB", "USB"]:
            return 0
        else:
            return 1

    @staticmethod
    def Halt() -> int:
        return 1

    @staticmethod
    def SetTagVal(tag: str, value: Union[int, float]) -> int:
        if isinstance(value, (np.int32, np.int64)):
            value = int(value)
        if not isinstance(tag, str):
            return 0
        if not isinstance(value, (int, float)):
            return 0
        else:
            return 1

    @staticmethod
    def GetTagVal(tag: str) -> int:
        if tag == "playback":  # return 0 so wait function won't block
            return 0
        if not isinstance(tag, str):
            return 0
        return 1

    @staticmethod
    def ReadTagV(tag: str, n_start: int, n_samples: int) -> Union[int, list]:
        if not isinstance(tag, str):
            return 0
        if not isinstance(n_start, int):
            return 0
        if not isinstance(n_start, int):
            return 0
        if n_samples == 1:
            return 1
        if n_samples > 1:
            return [random.random() for i in range(n_samples)]

    @staticmethod
    def zBusTrigA(rack_num: int, trig_type: int, delay: int) -> int:
        if not isinstance(rack_num, int):
            return 0
        if not isinstance(trig_type, int):
            return 0
        if not isinstance(delay, int):
            return 0
        return 1

    @staticmethod
    def zBusTrigB(rack_num: int, trig_type: int, delay: int) -> int:
        if not isinstance(rack_num, int):
            return 0
        if not isinstance(trig_type, int):
            return 0
        if not isinstance(delay, int):
            return 0
        return 1

    class _oleobj_:
        # this is a hack and should be fixed
        @staticmethod
        def InvokeTypes(arg1, arg2, arg3, arg4, arg5, tag, arg6, value):
            return 1
