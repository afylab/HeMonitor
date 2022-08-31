from PyQt5 import QtWidgets, QtCore, uic
from twisted.internet.defer import inlineCallbacks, Deferred
import pyqtgraph as pg
import numpy as np
from datetime import datetime, timedelta
import mysql.connector as mysql
import time

LevelWindowUI, QtBaseClass = uic.loadUiType(r"C:\Users\Cthulhu\Downloads\HeMonitor-master\HeMonitor-master\Level_Monitor_GUI.ui")

class CustomViewBox(pg.ViewBox):
    '''
    Viewbox that allows for selecting range, taken from PyQtGraphs documented examples
    '''
    def __init__(self, *args, **kwds):
        kwds['enableMenu'] = False
        pg.ViewBox.__init__(self, *args, **kwds)
        self.setMouseMode(self.RectMode)
    #

    ## reimplement right-click to zoom out
    def mouseClickEvent(self, ev):
        if ev.button() == QtCore.Qt.RightButton:
            self.autoRange()
    #

    ## reimplement mouseDragEvent to disable continuous axis zoom
    def mouseDragEvent(self, ev, axis=None):
        if axis is not None and ev.button() == QtCore.Qt.RightButton:
            ev.ignore()
        else:
            pg.ViewBox.mouseDragEvent(self, ev, axis=axis)
    #
#

class LevelMonitorGUI(QtWidgets.QMainWindow, LevelWindowUI):
    def __init__(self, reactor, params, parent=None):
        '''
        params is a dictionary containing the parameters for calculating the volume
        of Helium in real units. Requires parameters:
        'active length' : The active length (in inches) of the Helium sensor, for calculating %.
        'belly bottom level' : The number of inches indicating the bottom of the dewar belly
        'belly top level' : The number of inches indicating the top of the dewar belly
        'belly L per in' : Number of liters per inch in the belly (calculated with insert in).
        'tail L per in': Number of liters per inch in the belly (calculated with insert in).
        'fill level' : The level to fill once reached, used for calculating the time to fill.
        'default interval' : The default sampling interval.
        'System ID': The Identifier for the nanoSQUID system in datavault.
        '''
        super().__init__(parent)
        self.reactor = reactor
        self.params = params

        # data rows:
        # [time (h), level_in, level_%]
        self.data = np.empty((0,3))
        self.level = -1 # Last level of Helium in inches
        self.interval = self.params['default interval']
        self.fillmode = False
        self.t0 = datetime.now()
        self.fillstart = datetime.now()
        self.cxn = False
        self.lm = False

        self.setupUi(self)
        self.setupAdditionalUi()

        self.connectLabRAD()

    def setupAdditionalUi(self):
        #Set up UI that isn't easily done from Qt Designer
        self.setWindowTitle("He Level Monitor")

        self.levelPlot = pg.PlotWidget(self.frame_level_plot, viewBox=CustomViewBox())
        self.levelPlot.setGeometry(QtCore.QRect(0, 0, 500, 400))
        self.levelPlot.setLabel('left', 'Level', units = '%')
        self.levelPlot.setLabel('bottom', 'Time', units = 'h')
        self.levelPlot.showAxis('right', show = True)
        self.levelPlot.showAxis('top', show = True)
        self.levelPlot.setTitle('Liquid Helium Level vs. Time')
        self.curve = self.levelPlot.plot(self.data[:,0], self.data[:,1], pen=None, symbol='o', symbolBrush=(200,200,200), symbolPen='w', symbolSize=5)

        s = str(round(100*self.params['fill level']/self.params['active length'],1))
        self.label_fill_level.setText(s + " %")

        self.update_interval_button.clicked.connect(self.update_interval)
        self.measure_button.clicked.connect(self.measure_now_callback)
        self.fill_button.clicked.connect(self.toggle_fill_mode)

    @inlineCallbacks
    def connectLabRAD(self):
        try:
            from labrad.wrappers import connectAsync
            self.cxn = yield connectAsync('localhost', password='pass')
            self.lm = self.cxn.lm_510
            yield self.lm.select_device()
            if self.interval != 'manual':
                yield self.lm.set_sample_mode('S')
                yield self.lm.set_sample_interval(self.params['default interval'])
            else:
                yield self.lm.set_off_mode()
            yield self.lm.set_units("%")
            self.label_interval.setText(self.interval)

            self.dv = self.cxn.data_vault
            self.dv.set_nanosquid_system(self.params['nanosquid system'])

            date = datetime.now()
            datestamp = date.strftime("%Y-%m-%d %H:%M:%S")
            self.dv.new("LHe Level - "+datestamp, ["time (hours)"], ["volume (%)", "level (in)"])
            self.dv.add_parameter('Start date and time', datestamp)

            dset = yield self.dv.current_identifier()
            self.label_dv.setText(dset)

            self.label_server_status.setText("Connected")
            self.label_server_status.setStyleSheet("#label_server_status{" +
                "color: rgb(13, 192, 13);}")
            yield self.monitor()
        except:
            from traceback import print_exc
            print_exc()

    def disconnectLabRAD(self):
        self.monitoring = False
        self.cxn = False
        self.lm = False
        self.label_server_status.setText("Disconnected")
        self.label_server_status.setStyleSheet("#label_server_status{" +
            "color: rgb(144, 140, 9);}")

    @inlineCallbacks
    def monitor(self):
        self.monitoring = True

        print("Starting initial sample")
        yield self.lm.prep_measure()
        yield self.sleep(20)

        while self.monitoring:
            N = self.data.size
            try:
                current = yield self.lm.get_measure()
                percent = round(float(current.replace(" %","")),2)
                inches = round(float(percent*self.params['active length']/100),2)

                if inches != self.level:
                    t = (datetime.now() - self.t0).total_seconds()/3600.0
                    self.level = inches
                    self.dv.add((t, percent, inches))
                    self.data = np.append(self.data, [[t, percent, inches]], axis=0)
                    self.uploadToDatabase()
                    print(t, percent, inches)
            except:
                from traceback import print_exc
                print_exc()
                self.label_server_status.setText("Error")
                self.label_server_status.setStyleSheet("#label_server_status{" +
                    "color: rgb(200, 13, 13);}")
                self.monitoring = False

            if self.data.size > N: # If there is new data, update the interface.
                self.update_interface()
            self.update_time_remaining() # Always update the time remaining.

            # If been in fill mode more than 2 hours, go out of fill mode automatically
            if self.fillmode and (datetime.now()-self.fillstart).total_seconds() >= 7200:
                self.toggle_fillmode()

            yield self.sleep(10)
    #

    def update_interval(self,c):
        interval, done = QtWidgets.QInputDialog.getText(self, 'Sample Interval', "Enter Sampleing Interval as 00:00:00")
        if done:
            s = interval.split(':')
            if len(s) == 3 and all(i.isdigit() for i in s) and all(float(i) <= 59 for i in s):
                self.interval = interval
                self.update_sampling_interval()
            if interval == 'manual':
                self.interval = interval
                self.label_interval.setText(self.interval)
                self.lm.set_off_mode()
    #

    @inlineCallbacks
    def update_sampling_interval(self):
        self.label_interval.setText(self.interval)
        yield self.lm.set_sample_interval(self.interval)

    @inlineCallbacks
    def measure_now_callback(self,c):
        mode = yield self.lm.get_mode()
        if mode == 'Off':
            yield self.lm.set_sample_mode('S')
            yield self.lm.prep_measure()
            time.sleep(5)
            yield self.lm.prep_measure()

            time.sleep(2)
            yield self.lm.set_off_mode()
        else:
            yield self.lm.prep_measure()
    #

    def toggle_fill_mode(self):
        if self.fillmode:
            self.fillmode = False
            self.interval = self.params['default interval']
            self.update_sampling_interval()
            self.fill_button.setStyleSheet("#fill_button{" +
                "color: rgb(168,168,168);font-size:14pt;}")
        else:
            self.fillmode = True
            self.fillstart = datetime.now()
            self.interval = self.params['fillmode interval']
            self.update_sampling_interval()
            self.fill_button.setStyleSheet("#fill_button{" +
                "color: rgb(0, 200, 0);font-size:14pt;}")
    #

    def update_interface(self):
        try:
            self.label_level.setText(str(round(self.level,2)) + " in")
            pcnt = str(round(100*self.level/self.params['active length'],2))
            self.label_level_percent.setText(pcnt + " %")

            if self.level < self.params['belly bottom level']: # Level is in the tail
                volume = self.level*self.params['tail L per in']
            else:
                volume_in_tail = self.params['belly bottom level']*self.params['tail L per in']
                inches_in_belly = self.level - self.params['belly bottom level']
                volume = volume_in_tail + inches_in_belly*self.params['belly L per in']
            self.label_volume.setText(str(int(volume)) + " L")

            self.curve.setData(x=self.data[:,0], y=self.data[:,1])
            rows, cols = self.data.shape

            if rows > 1:
                self.recent = (self.data[rows-1,1] - self.data[rows-2,1])/(self.data[rows-1,0] - self.data[rows-2,0])
                self.label_change.setText(str(round(self.recent,2)) + " %/hour")

            if rows > 1 and not self.fillmode:
                # Identify the points to include in the fit to calculate He consumption
                # First consider the points in the last 24 hours
                # Check that there are enough points in the last 24 hours and they are overall decreasing (to exclude fills)
                ix24 = np.searchsorted(self.data[:,0], self.data[rows-1,0]-24)
                if ix24 < rows-1 and np.mean(np.diff(self.data[ix24:,1])) < 0:
                    ix1 = ix24
                else: # the default case, consider the last 4 data points
                    ix1 = max([rows-4, 0])
                self.linfit = np.polyfit(self.data[ix1:,0], self.data[ix1:,1], 1)
                # self.rate24hr = self.linfit[0]*self.params['active length']*self.params['belly L per in']/100
                self.label_rate.setText(str(round(self.linfit[0],2)) + " %/hour")

                # Plot the 24-hour fit
                if hasattr(self, 'fit'):
                    self.fit.clear() # Clear the old fit
                self.fit = self.levelPlot.plot(self.data[ix1:,0], np.polyval(self.linfit, self.data[ix1:,0]), pen=(200,200,200))

            if self.data[rows-1,0] > 72 and not self.fillmode:
                self.levelPlot.setXRange(self.data[rows-1,0]-72, self.data[rows-1,0])
            elif self.fillmode:
                self.levelPlot.setXRange(self.data[rows-1,0]-2, self.data[rows-1,0])
        except:
            from traceback import print_exc
            print_exc()
    #

    def update_time_remaining(self):
        # Time remaining until fill (in hours)
        if not hasattr(self, "linfit"):
            return
        levelnow = np.polyval(self.linfit, (datetime.now()-self.t0).total_seconds()//3600)
        tfill = (levelnow*self.params['active length']/100 - self.params['fill level'])/(np.abs(self.linfit[0])*self.params['active length']/100)
        if tfill > 0:
            days = max([int(tfill // 24), 0])
            hours = max([int(tfill % 24), 0])
        else:
            days = 0
            hours = 0
        if tfill >= 24:
            self.label_time.setStyleSheet("#label_time{" +
                "color: rgb(168, 168, 168);font-size:14pt;}")
        elif tfill < 24 and tfill > 1:
            self.label_time.setStyleSheet("#label_time{" +
                "color: rgb(200, 200, 0);font-size:14pt;}")
        else:
            self.label_time.setStyleSheet("#label_time{" +
                "color: rgb(200, 0, 0);font-size:14pt;}")
        self.label_time.setText(str(days) + " days, " + str(hours) + " hours")

    # Below function is not necessary, but is often useful. Yielding it will provide an asynchronous
    # delay that allows other labrad / pyqt methods to run
    def sleep(self,secs):
        """Asynchronous compatible sleep command. Sleeps for given time in seconds, but allows
        other operations to be done elsewhere while paused."""
        d = Deferred()
        self.reactor.callLater(secs,d.callback,'Sleeping')
        return d

    def uploadToDatabase(self):
        try:
            values = self.data
            #values = getTheErrayOfValues(data)
            # print('connecting to MySql')
            conn = mysql.connect(host='gator4099.hostgator.com', user='afy2003_15K_systemBot', passwd='rwnVv3%MXns3j;X{',
                                 database='afy2003_15K_system')
            # print("connection has been established")
            cursor = conn.cursor()
            now = datetime.now()
            formatted_date = now.strftime('%Y%m%d%H%M%S')
            if self.level < self.params['belly bottom level']: # Level is in the tail
                volume = self.level*self.params['tail L per in']
            else:
                volume_in_tail = self.params['belly bottom level']*self.params['tail L per in']
                inches_in_belly = self.level - self.params['belly bottom level']
                volume = volume_in_tail + inches_in_belly*self.params['belly L per in']
            try:
                cursor.execute("INSERT INTO Status VALUES (%s,%s,%s,%s)",(str(100*self.level/self.params['active length']), str(self.level), str(int(volume)), str(formatted_date)))
                conn.commit()
            except mysql.Error as err:
                print("Something went wrong: {}".format(err))
            conn.close()
        except Exception as e:
            print(e)
