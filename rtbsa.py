#!/usr/local/lcls/package/python/current/bin/python
# Written by Zimmer, refactored by Lisa

import sys

from epics import caget, PV

import numpy as np
from numpy import polyfit, poly1d, polyval, corrcoef, std, mean
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from subprocess import CalledProcessError

from logbook import *

from rtbsa_ui import Ui_RTBSA

from Constants import *

from itertools import compress


class RTBSA(QMainWindow):
    def __init__(self, parent=None):
        QMainWindow.__init__(self, parent)
        self.ui = Ui_RTBSA()
        self.ui.setupUi(self)
        self.setWindowTitle('Real Time BSA')
        self.loadStyleSheet()
        self.setUpGraph()

        QObject.connect(self.ui.enter1, SIGNAL("textChanged(const QString&)"),
                        self.searchA)
        QObject.connect(self.ui.enter2, SIGNAL("textChanged(const QString&)"),
                        self.searchB)

        self.ui.listWidget.itemClicked.connect(self.setenterA)
        self.ui.listWidget_2.itemClicked.connect(self.setenterB)

        self.bsapvs = ['GDET:FEE1:241:ENRC', 'GDET:FEE1:242:ENRC',
                       'GDET:FEE1:361:ENRC', 'GDET:FEE1:362:ENRC']

        # Generate list of BSA PVS
        try:
            BSAPVs = check_output(['eget', '-ts', 'ds', '-a',
                                   'tag=LCLS.BSA.rootnames']).splitlines()[1:-1]
            self.bsapvs = self.bsapvs + BSAPVs

        # Backup for timeout error
        except CalledProcessError:
            print "Unable to pull most recent PV list"
            self.bsapvs = self.bsapvs + bsapvs

        for pv in self.bsapvs:
            self.ui.listWidget.addItem(pv)
            self.ui.listWidget_2.addItem(pv)

        self.ui.common1.addItems(commonlist)
        self.ui.common2.addItems(commonlist)
        self.ui.common1.setCurrentIndex(28)
        self.ui.common1.activated.connect(self.commonactivated)
        self.ui.common2.activated.connect(self.commonactivated)
        self.ui.AvsB.clicked.connect(self.AvsBClick)
        self.ui.draw_button.clicked.connect(self.on_draw)
        self.ui.stop_button.clicked.connect(self.stop)
        self.ui.log_button.clicked.connect(self.logbook)
        self.ui.mcclog_button.clicked.connect(self.MCCLog)
        self.ui.avg_cb.clicked.connect(self.avg_click)
        self.ui.std_cb.clicked.connect(self.std_click)
        self.ui.corr_cb.clicked.connect(self.corr_click)
        self.ui.parab_cb.clicked.connect(self.parab_click)
        self.ui.line_cb.clicked.connect(self.line_click)
        self.ui.fitedit.returnPressed.connect(self.fitorderactivated)
        self.ui.common1_rb.clicked.connect(self.common_1_click)
        self.ui.common2_rb.clicked.connect(self.common_2_click)
        self.ui.enter1_rb.clicked.connect(self.enter_1_click)
        self.ui.enter2_rb.clicked.connect(self.enter_2_click)
        self.ui.AvsT_cb.clicked.connect(self.AvsTClick)
        self.ui.AFFT.clicked.connect(self.AFFTClick)
        self.ui.enter1.returnPressed.connect(self.commonactivated)
        self.ui.enter2.returnPressed.connect(self.commonactivated)
        self.ui.points.returnPressed.connect(self.points_entered)

        # Initial number of points
        self.numpoints = 2800

        # 20ms polling time
        self.updatetime = 20

        # Set initial polynomial fit to 2
        self.fitorder = 2

        self.dpi = 100

        self.ui.fitedit.setDisabled(True)
        self.ui.enter1.setDisabled(True)
        self.ui.enter2.setDisabled(True)
        self.ui.label.setDisabled(True)
        self.ui.listWidget.setDisabled(True)
        self.ui.listWidget_2.setDisabled(True)
        self.statusBar().showMessage('Hi there!  I missed you!')
        self.abort = True
        self.ui.parab_cb.setChecked(False)

        # Used to update plot
        self.timer = QTimer(self)

        self.rate = PV('EVNT:SYS0:1:LCLSBEAMRATE')
        self.menuBar().setStyleSheet('QWidget{background-color:grey;color:purple}')
        self.create_menu()
        self.create_status_bar()

        self.devices = {"A": None, "B": None}

    def setUpGraph(self):
        self.plot = pg.PlotWidget(alpha=0.75)
        layout = QGridLayout()
        self.ui.widget.setLayout(layout)
        layout.addWidget(self.plot, 0, 0)
        self.plot.showGrid(1, 1)

    def loadStyleSheet(self):
        try:
            self.cssfile = "/home/physics/zimmerc/python/style.css"
            with open(self.cssfile, "r") as f:
                self.setStyleSheet(f.read())
        except:
            print "Error loading style sheet"
            pass

    def create_status_bar(self):
        self.status_text = QLabel()
        palette = QPalette()
        palette.setColor(palette.Foreground, Qt.magenta)
        self.statusBar().addWidget(self.status_text, 1)
        self.statusBar().setPalette(palette)

    # Effectively an autocomplete
    def search(self, enter, widget):
        widget.clear()
        query = str(enter.text())
        for pv in self.bsapvs:
            if query.lower() in pv.lower():
                widget.addItem(pv)

    def searchA(self):
        self.search(self.ui.enter1, self.ui.listWidget)

    def searchB(self):
        self.search(self.ui.enter2, self.ui.listWidget_2)

    def setEnter(self, widget, enter, search, enter_rb):
        selection = widget.currentItem()
        enter.textChanged.disconnect()
        enter.setText(selection.text())
        QObject.connect(enter, SIGNAL("textChanged(const QString&)"), search)
        if not self.abort and enter_rb.isChecked():
            self.stop()
            self.on_draw()

    def setenterA(self):
        self.setEnter(self.ui.listWidget, self.ui.enter1, self.searchA,
                      self.ui.enter1_rb)

    def setenterB(self):
        self.setEnter(self.ui.listWidget_2, self.ui.enter2, self.searchB,
                      self.ui.enter2_rb)

    def correctNumpoints(self, errorMessage, acceptableValue):
        self.statusBar().showMessage(errorMessage, 6000)
        self.numpoints = acceptableValue
        self.ui.points.setText(str(acceptableValue))

    def points_entered(self):
        try:
            self.numpoints = int(self.ui.points.text())
        except ValueError:
            self.correctNumpoints('Enter an integer, 1 to 2800', 120)
            return

        if self.numpoints > 2800:
            self.correctNumpoints('Max # points is 2800', 2800)
            return

        if self.numpoints < 1:
            self.correctNumpoints('Min # points is 1', 1)
            return

        self.reinitialize_plot()

    def populateDevices(self, common_rb, common, enter_rb, enter, device):

        # HSTBR is what gets the beam synchronous data
        if common_rb.isChecked():
            self.devices[device] = str(common.currentText()) + 'HSTBR'

        elif enter_rb.isChecked():
            pv = str(enter.text()).strip()
            # Checks that it's non empty and that it's a BSA pv
            if pv and pv in self.bsapvs:
                self.devices[device] = str(enter.text()) + 'HSTBR'
            else:
                self.statusBar().showMessage('Device ' + device
                                             + ' invalid. Aborting.', 10000)
                self.ui.draw_button.setEnabled(True)
                return False

        return True

    ############################################################################
    # Time 1 is when Device A started acquiring data, and Time 2 is when Device
    # B started acquiring data. Since they're not guaranteed to start
    # acquisition at the same time, one data buffer might be ahead of the other,
    # meaning that the intersection of the two buffers would not include the
    # first n elements of one and the last n elements of the other. See the
    # diagram below, where the dotted line represents the time axis (one buffer
    # is contained  by square brackets [], the other by curly braces {}, and the
    # times where each starts  and ends is indicated right underneath).
    #
    #
    #          [           {                            ]           }
    # <----------------------------------------------------------------------> t
    #       t1_start    t2_start                     t1_end      t2_end
    #
    #
    # Note that both buffers are of the same size (self.numpoints) so that:
    # (t1_end - t1_start) = (t2_end - t2_start)
    #
    # From the diagram, we see that only the time between t2_start and t1_end
    # contains data from both buffers (t1_start to t2_start only contains data
    # from buffer 1, and t1_end to t2_end only contains data from buffer 2).
    # Using that, we can chop the beginning of buffer 1 and the end of buffer 2
    # so that we're only left with the overlapping region.
    #
    # In order to figure out how many points we need to chop from each buffer
    # (it's the same number for both since they're both the same size), we
    # multiply the time delta by the beam rate (yay dimensional analysis!):
    # seconds * (shots/second) = (number of shots)
    ############################################################################
    def setValSynced(self):

        numBadShots = round((self.time2 - self.time1) * self.rate.value)

        # Gets opposite indices depending on which time is greater (and [0:2800]
        # if they're equal)
        val1synced = self.val1pre[max(0, numBadShots)
                                  :min(2800, 2800 + numBadShots)]
        val2synced = self.val2pre[max(0, -numBadShots)
                                  :min(2800, 2800 - numBadShots)]

        return [abs(numBadShots), val1synced, val2synced]

    def updateRate(self):
        # self.rate is a PV, such that .value is shorthand for .getval
        rate = self.rate.value
        while rate not in [120.0, 60.0, 30.0, 10.0]:
            QApplication.processEvents()
            rate = self.rate.value
        return rate

    def cleanPlot(self):
        self.plot.clear()

        self.avg_text = pg.TextItem('', color=(200, 200, 250), anchor=(0, 1))
        self.std_text = pg.TextItem('', color=(200, 200, 250), anchor=(0, 1))
        self.slope_text = pg.TextItem('', color=(200, 200, 250), anchor=(0, 1))
        self.corr_text = pg.TextItem('', color=(200, 200, 250), anchor=(0, 1))

        plotLabels = [self.avg_text, self.std_text, self.slope_text,
                      self.corr_text]

        for plotLabel in plotLabels:
            self.plot.addItem(plotLabel)

    def getData(self):
        # If i use Popen instead of pyepics caget, the program doesn't
        # start lagging if you change PVs (?!?!?). Some stupid bug in 
        # new pyepics.
        getdata = Popen("caget " + self.fullPVName, stdout=PIPE, shell=True)
        newdata = str(getdata.communicate()).split()[2:-1]
        newdata[-1] = newdata[-1][:-4]
        return [float(i) for i in newdata]

    def initializeData(self):
        self.statusBar().showMessage('Initializing...')

        if self.ui.common1_rb.isChecked():
            self.fullPVName = str(self.ui.common1.currentText() + 'HSTBR')

        elif self.ui.enter1_rb.isChecked():
            pv = str(self.ui.enter1.text()).strip()
            if pv and pv in self.bsapvs:
                self.fullPVName = pv + 'HSTBR'
            else:
                return None
        else:
            return None

        return self.getData()

    def adjustVals(self):
        self.updateRate()
        numBadShots, self.dataBufferA, self.dataBufferB = self.setValSynced()

        blength = 2800 - numBadShots

        # Make sure the buffer size doesn't exceed the desired number of points
        if (self.numpoints < blength):
            self.dataBufferA = self.dataBufferA[blength - self.numpoints:blength]
            self.dataBufferB = self.dataBufferB[blength - self.numpoints:blength]

    def updateValsFromInput(self):

        if not self.populateDevices(self.ui.common1_rb, self.ui.common1,
                                    self.ui.enter1_rb, self.ui.enter1, "A"):
            return

        if not self.populateDevices(self.ui.common2_rb, self.ui.common2,
                                    self.ui.enter2_rb, self.ui.enter2, "B"):
            return

        self.dataBufferA, self.dataBufferB = [], []

        # Without the time parameter, we wouldn't get the timestamp
        self.val1pv = PV(self.devices["A"], form='time')
        self.val2pv = PV(self.devices["B"], form='time')

        self.statusBar().showMessage('Initializing/Syncing (be patient, '
                                     + 'may take 5 seconds)...')

        self.time1, self.time2 = None, None

        # For some reason, callbacks are the only way to get a timestamp
        self.val1CallbackIndex = self.val1pv.add_callback(self.val1Callback)
        self.val2CallbackIndex = self.val2pv.add_callback(self.val2Callback)

        while (not self.time1 or not self.time2) and not self.abort:
            QApplication.processEvents()

        self.adjustVals()

    def getLinearFit(self, xdata, ydata, updateExistingPlot):
        try:
            (m, b) = polyfit(xdata, ydata, 1)
            fitdata = polyval([m, b], xdata)
            m = "{:.3e}".format(m)
            self.slope_text.setText('Slope: ' + str(m))
            if updateExistingPlot:
                self.fit.setData(xdata, fitdata)
            else:
                self.fit = pg.PlotCurveItem(xdata, fitdata, 'g-', linewidth=1)
        except:
            print "Error getting linear fit"
            pass

    def getPolynomialFit(self, xdata, ydata, updateExistingPlot):
        try:
            co = polyfit(xdata, ydata, self.fitorder)
            pol = poly1d(co)
            sorted1 = sorted(xdata)
            fit = pol(sorted1)

            if updateExistingPlot:
                self.parab.setData(sorted1, fit)
            else:
                self.parab = pg.PlotCurveItem(xdata, fit, pen=3)

            if self.fitorder == 2:
                self.slope_text.setText('Peak: ' + str(-co[1] / (2 * co[0])))

            elif self.fitorder == 3:
                self.slope_text.setText(str("{:.2e}".format(co[0])) + 'x^3'
                                        + str("+{:.2e}".format(co[1])) + 'x^2'
                                        + str("+{:.2e}".format(co[2])) + 'x'
                                        + str("+{:.2e}".format(co[3])))

        except np.linalg.linalg.LinAlgError:
            print "Linear algebra error getting curve fit"
            pass
        except:
            self.slope_text.setText('Fit failed')
            pass

    def plotFit(self, xdata, ydata, title):
        self.plot.addItem(self.curve)
        self.plot.setTitle(title)

        # Fit line
        if self.ui.line_cb.isChecked():
            self.getLinearFit(xdata, ydata, False)
            self.plot.addItem(self.fit)

        # Fit polynomial
        elif self.ui.parab_cb.isChecked():
            self.ui.fitedit.setDisabled(False)
            self.getPolynomialFit(xdata, ydata, False)
            self.plot.addItem(self.parab)

    def genTimePlotA(self):
        newdata = self.initializeData()

        if not newdata:
            self.statusBar().showMessage('Invalid PV? Unable to get data.'
                                         + ' Aborting.', 10000)
            self.ui.draw_button.setEnabled(True)
            return

        self.curve = pg.PlotCurveItem(newdata[2800 - self.numpoints:2800],
                                      pen=1)
        self.plot.addItem(self.curve)

        self.xdata = range(self.numpoints)

        self.plotFit(self.xdata, newdata[2800 - self.numpoints:2800],
                     self.fullPVName)

    def genABPlot(self):

        self.curve = pg.ScatterPlotItem(self.dataBufferA, self.dataBufferB,
                                        pen=1, symbol='x', size=5)
        self.plot.addItem(self.curve)

        self.plotFit(self.dataBufferA, self.dataBufferB,
                     self.devices["B"] + ' vs. ' + self.devices["A"])

    def genFFTPlot(self):
        newdata = self.initializeData()

        if not newdata:
            return

        newdata = newdata[2800 - self.numpoints:2800]
        newdata.extend(np.zeros(self.numpoints * 2).tolist())
        newdata = newdata - np.mean(newdata);
        ps = np.abs(np.fft.fft(newdata)) / len(newdata)
        self.FS = self.rate.value
        self.freqs = np.fft.fftfreq(len(newdata), 1.0 / self.FS)
        self.keep = self.freqs >= 0
        ps = ps[self.keep]
        self.freqs = self.freqs[self.keep]
        self.idx = np.argsort(self.freqs)
        self.curve = pg.PlotCurveItem(x=self.freqs[self.idx],
                                      y=ps[self.idx], pen=1)
        self.plot.addItem(self.curve)
        self.plot.setTitle(self.fullPVName)

    def genPlotAndSetTimer(self, genPlot, updateMethod):
        if self.abort:
            return

        try:
            genPlot()
        except UnboundLocalError:
            self.statusBar().showMessage('No Data, Aborting Plotting Algorithm',
                                         10000)
            return

        self.timer = QTimer(self)
        self.timer.singleShot(self.updatetime, updateMethod)
        self.statusBar().showMessage('Running')

    # Where the magic happens(well, where it starts to happen). This initializes
    # the BSA plotting and then starts a timer to update the plot.
    def on_draw(self):
        plotTypeIsValid = (self.ui.AvsT_cb.isChecked()
                           or self.ui.AvsB.isChecked()
                           or self.ui.AFFT.isChecked())

        if not plotTypeIsValid:
            self.statusBar().showMessage('Pick a Plot Type (PV vs. time or B vs A)',
                                         10000)
            return

        self.ui.draw_button.setDisabled(True)
        self.abort = False

        self.cleanPlot()

        ####Plot history buffer for one PV####
        if self.ui.AvsT_cb.isChecked():
            self.genPlotAndSetTimer(self.genTimePlotA, self.update_plot_HSTBR)

        ####Plot for 2 PVs####
        elif self.ui.AvsB.isChecked():
            self.updateValsFromInput()
            self.genPlotAndSetTimer(self.genABPlot, self.update_BSA_Plot)

        ####Plot power spectrum####
        else:
            self.genPlotAndSetTimer(self.genFFTPlot, self.update_plot_FFT)

    def filterData(self, dataBuffer, key):
        if self.devices[key] == "BLEN:LI24:886HSTBR":
            filterFunc = lambda x: not np.isnan(x) and x < 12000
        else:
            filterFunc = lambda x: not np.isnan(x)

        mask = [filterFunc(x) for x in dataBuffer]
        self.dataBufferA = list(compress(self.dataBufferA, mask))
        self.dataBufferB = list(compress(self.dataBufferB, mask))

    # Need to filter out errant indices from both buffers to keep them
    # synchronized
    def filterVals(self):
        self.filterData(self.dataBufferA, "A")
        self.filterData(self.dataBufferB, "B")

    def setPlotRanges(self):
        if self.ui.autoscale_cb.isChecked():
            mx = np.max(self.dataBufferB)
            mn = np.min(self.dataBufferB)

            if mn != mx:
                self.plot.setYRange(mn, mx)

            mx = np.max(self.dataBufferA)
            mn = np.min(self.dataBufferA)

            if mn != mx:
                self.plot.setXRange(mn, mx)

    def setPosAndText(self, attribute, value, posValX, posValY, textVal):
        value = "{:.3}".format(value)
        attribute.setPos(posValX, posValY)
        attribute.setText(textVal + str(value))

    def update_BSA_Plot(self):
        QApplication.processEvents()

        if self.abort:
            return

        self.plot.showGrid(self.ui.grid_cb.isChecked(),
                           self.ui.grid_cb.isChecked())

        self.adjustVals()
        self.filterVals()

        self.curve.setData(self.dataBufferA, self.dataBufferB)

        self.setPlotRanges()

        # Logic to determine positions of labels when not running autoscale
        if self.ui.avg_cb.isChecked():
            self.setPosAndText(self.avg_text, mean(self.dataBufferB),
                               min(self.dataBufferA), min(self.dataBufferB),
                               'AVG: ')

        if self.ui.std_cb.isChecked():
            val1Min = min(self.dataBufferA)
            xPos = (val1Min + (val1Min + max(self.dataBufferA))/2)/2

            self.setPosAndText(self.std_text, std(self.dataBufferB), xPos,
                               min(self.dataBufferB), 'STD: ')

        if self.ui.corr_cb.isChecked():
            correlation = corrcoef(self.dataBufferA, self.dataBufferB)
            self.setPosAndText(self.corr_text, correlation, min(self.dataBufferA),
                               max(self.dataBufferB), "Corr. Coefficient: ")

        if self.ui.line_cb.isChecked():
            self.slope_text.setPos((min(self.dataBufferA) + max(self.dataBufferA))/2,
                                   min(self.dataBufferB))
            self.getLinearFit(self.dataBufferA, self.dataBufferB, True)

        elif self.ui.parab_cb.isChecked():
            self.slope_text.setPos((min(self.dataBufferA) + max(self.dataBufferA)) / 2,
                                   min(self.dataBufferB))
            self.getPolynomialFit(self.dataBufferA, self.dataBufferB, True)

        self.timer.singleShot(self.updatetime, self.update_BSA_Plot)

    def update_plot_HSTBR(self):

        self.plot.showGrid(self.ui.grid_cb.isChecked(),
                           self.ui.grid_cb.isChecked())

        QApplication.processEvents()

        if self.abort:
            return

        chopped = self.getData()[2800 - self.numpoints:2800]
        self.curve.setData(chopped)

        if self.ui.autoscale_cb.isChecked():
            mx = max(chopped)
            mn = min(chopped)
            if mx - mn > .00001:
                self.plot.setYRange(mn, mx)
                self.plot.setXRange(0, len(chopped))

        if self.ui.avg_cb.isChecked():
            self.setPosAndText(self.avg_text, mean(chopped), 0, min(chopped),
                               'AVG: ')

        if self.ui.std_cb.isChecked():
            self.setPosAndText(self.std_text, std(chopped), self.numpoints/4,
                               min(chopped), 'STD: ')

        if self.ui.corr_cb.isChecked():
            self.corr_text.setText('')

        if self.ui.line_cb.isChecked():
            self.slope_text.setPos(self.numpoints / 2, min(chopped))
            self.getLinearFit(self.xdata, chopped, True)

        elif self.ui.parab_cb.isChecked():
            self.slope_text.setPos(self.numpoints / 2, min(chopped))
            self.getPolynomialFit(self.xdata, chopped, True)

        self.timer.singleShot(40, self.update_plot_HSTBR)

    def update_plot_FFT(self):
        self.plot.showGrid(self.ui.grid_cb.isChecked(),
                           self.ui.grid_cb.isChecked())
        QApplication.processEvents()

        if self.abort:
            return

        newdata = self.getData()
        newdata = newdata[2800 - self.numpoints:2800]
        newdata = np.array(newdata)
        nans, x = np.isnan(newdata), lambda z: z.nonzero()[0]
        # interpolate nans
        newdata[nans] = np.interp(x(nans), x(~nans), newdata[~nans])
        newdata = newdata - np.mean(newdata);
        newdata = newdata.tolist()
        newdata.extend(np.zeros(self.numpoints * 2).tolist())
        ps = np.abs(np.fft.fft(newdata)) / len(newdata)
        self.FS = self.rate.value
        self.freqs = np.fft.fftfreq(len(newdata), 1.0 / self.FS)
        self.keep = (self.freqs >= 0)
        ps = ps[self.keep]
        self.freqs = self.freqs[self.keep]
        self.idx = np.argsort(self.freqs)
        self.curve.setData(x=self.freqs[self.idx], y=ps[self.idx])

        if self.ui.autoscale_cb.isChecked():
            mx = max(ps)
            mn = min(ps)
            if mx - mn > .00001:
                self.plot.setYRange(mn, mx)
                self.plot.setXRange(min(self.freqs), max(self.freqs))

        self.timer.singleShot(40, self.update_plot_FFT)

    # Callback function for PV1
    def val1Callback(self, pvname=None, value=None, timestamp=None, **kw):
        self.time1 = timestamp
        self.val1pre = value

    # Callback function for PV2
    def val2Callback(self, pvname=None, value=None, timestamp=None, **kw):
        self.time2 = timestamp
        self.val2pre = value

    def AvsTClick(self):
        if not self.ui.AvsT_cb.isChecked():
            pass
        else:
            self.ui.AvsB.setChecked(False)
            self.ui.AFFT.setChecked(False)
            self.AvsBClick()

    def AvsBClick(self):
        if not self.ui.AvsB.isChecked():
            self.ui.groupBox_2.setDisabled(True)
            self.ui.enter2_rb.setChecked(False)
            self.ui.enter2_rb.setDisabled(True)
            self.ui.enter2.setDisabled(True)
            self.ui.common2.setDisabled(True)
            self.ui.common2_rb.setChecked(False)
            self.ui.common2_rb.setDisabled(True)
        else:
            self.ui.AvsT_cb.setChecked(False)
            self.ui.AFFT.setChecked(False)
            self.AvsTClick()
            self.ui.groupBox_2.setDisabled(False)
            self.ui.listWidget_2.setDisabled(True)
            self.ui.enter2_rb.setDisabled(False)
            self.ui.enter2.setDisabled(True)
            self.ui.common2_rb.setDisabled(False)
            self.ui.common2_rb.setChecked(True)
            self.ui.common2.setDisabled(False)
        self.stop()

    def AFFTClick(self):
        if not self.ui.AFFT.isChecked():
            pass
        else:
            self.ui.AvsB.setChecked(False)
            self.ui.AvsT_cb.setChecked(False)
            self.AvsBClick()

    def avg_click(self):
        if not self.ui.avg_cb.isChecked():
            self.avg_text.setText('')

    def std_click(self):
        if not self.ui.std_cb.isChecked():
            self.std_text.setText('')

    def corr_click(self):
        if not self.ui.corr_cb.isChecked():
            self.corr_text.setText('')

    def enter_1_click(self):
        if self.ui.enter1_rb.isChecked():
            self.ui.enter1.setDisabled(False)
            self.ui.listWidget.setDisabled(False)
            self.ui.common1_rb.setChecked(False)
            self.ui.common1.setDisabled(True)
        else:
            self.ui.enter1.setDisabled(True)

    def enter_2_click(self):
        if self.ui.enter2_rb.isChecked():
            self.ui.enter2.setDisabled(False)
            self.ui.listWidget_2.setDisabled(False)
            self.ui.common2_rb.setChecked(False)
            self.ui.common2.setDisabled(True)
        else:
            self.ui.enter2.setDisabled(True)

    def common_1_click(self):
        if self.ui.common1_rb.isChecked():
            self.ui.common1.setEnabled(True)
            self.ui.enter1_rb.setChecked(False)
            self.ui.enter1.setDisabled(True)
            self.ui.listWidget.setDisabled(True)
        else:
            self.ui.common1.setEnabled(False)
        self.commonactivated()

    def commonactivated(self):
        if not self.abort:
            self.stop()
            self.timer.singleShot(150, self.on_draw)

    def common_2_click(self):
        if self.ui.common2_rb.isChecked():
            self.ui.common2.setEnabled(True)
            self.ui.enter2_rb.setChecked(False)
            self.ui.enter2.setDisabled(True)
            self.ui.listWidget_2.setDisabled(True)
        else:
            self.ui.common2.setEnabled(False)
        self.commonactivated()

    def line_click(self):
        self.ui.parab_cb.setChecked(False)
        self.ui.fitedit.setDisabled(True)
        self.ui.label.setDisabled(True)
        self.reinitialize_plot()

    def fitorderactivated(self):
        try:
            self.fitorder = int(self.ui.fitedit.text())
        except ValueError:
            self.statusBar().showMessage('Enter an integer, 1-10', 6000)
            return

        if self.fitorder > 10 or self.fitorder < 1:
            self.statusBar().showMessage('Really?  That is going to be useful'
                                         + ' to you?  The (already ridiculous)'
                                         + ' range is 1-10.  Hope you win a '
                                         + 'nobel prize jackass.', 6000)
            self.ui.fitedit.setText('2')
            self.fitorder = 2

        if self.fitorder != 2:
            try:
                self.slope_text.setText('')
            except AttributeError:
                pass

    def parab_click(self):
        self.ui.line_cb.setChecked(False)

        if not self.ui.parab_cb.isChecked():
            self.ui.fitedit.setDisabled(True)
            self.ui.label.setDisabled(True)
        else:
            self.ui.fitedit.setEnabled(True)
            self.ui.label.setEnabled(True)
        self.reinitialize_plot()

    # This is a mess, but it works (used if user changes number points, 
    # fit type etc.) 
    def reinitialize_plot(self):
        self.cleanPlot()

        try:
            # Setup for single PV plotting
            if self.ui.AvsT_cb.isChecked():
                self.genTimePlotA()

            elif self.ui.AvsB.isChecked():
                self.genABPlot()
            else:
                newdata = self.getData()
                newdata = newdata[2800 - self.numpoints:2800]
                newdata.extend(np.zeros(self.numpoints * 2).tolist())
                newdata = newdata - np.mean(newdata);
                ps = np.abs(np.fft.fft(newdata)) / len(newdata)
                rate = {4: 1, 5: 10, 6: 30, 7: 60, 8: 120}
                i = caget('IOC:BSY0:MP01:BYKIK_RATE')
                self.FS = rate[i];
                self.freqs = np.fft.fftfreq(self.numpoints, 1.0 / self.FS)
                self.keep = (self.freqs >= 0)
                self.freqs = self.freqs[self.keep]
                ps = ps[self.keep]
                self.idx = np.argsort(self.freqs)
                self.curve = pg.PlotCurveItem(x=self.freqs[self.idx],
                                              y=ps[self.idx], pen=1)
                self.plot.addItem(self.curve)
                self.plot.setTitle(self.fullPVName)

        except:
            print "Error reinitializing plot"
            pass

    def logbook(self):
        logbook('Python Real-Time BSA', 'BSA Data',
                str(self.numpoints) + ' points', self.plot.plotItem)
        self.statusBar().showMessage('Sent to LCLS Physics Logbook!', 10000)

    def MCCLog(self):
        MCCLog('/tmp/RTBSA.png', '/tmp/RTBSA.ps', self.plot.plotItem)

    def stop(self):
        self.abort = True
        self.statusBar().showMessage('Stopped')
        self.ui.draw_button.setDisabled(False)
        QApplication.processEvents()

        try:
            self.val1pv.remove_callback(index=self.val1CallbackIndex)
            self.val1pv.disconnect()
        except:
            self.statusBar().showMessage('Stopped')

        try:
            self.val2pv.remove_callback(index=self.val2CallbackIndex)
            self.val2pv.disconnect()
        except:
            self.statusBar().showMessage('Stopped')

    def create_menu(self):
        self.file_menu = self.menuBar().addMenu("&File")

        load_file_action = self.create_action("&Save plot",
                                              shortcut="Ctrl+S",
                                              slot=self.save_plot,
                                              tip="Save the plot")

        quit_action = self.create_action("&Quit", slot=self.close,
                                         shortcut="Ctrl+Q",
                                         tip="Close the application")

        self.add_actions(self.file_menu,
                         (load_file_action, None, quit_action))

        self.help_menu = self.menuBar().addMenu("&Help")

        about_action = self.create_action("&About", shortcut='F1',
                                          slot=self.on_about, tip='About')

        self.add_actions(self.help_menu, (about_action,))

    def add_actions(self, target, actions):
        for action in actions:
            if action is None:
                target.addSeparator()
            else:
                target.addAction(action)

    def create_action(self, text, slot=None, shortcut=None, icon=None, tip=None,
                      checkable=False, signal="triggered()"):

        action = QAction(text, self)

        if icon is not None:
            action.setIcon(QIcon(":/%s.png" % icon))
        if shortcut is not None:
            action.setShortcut(shortcut)
        if tip is not None:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        if slot is not None:
            self.connect(action, SIGNAL(signal), slot)
        if checkable:
            action.setCheckable(True)
        return action

    def save_plot(self):
        file_choices = "PNG (*.png)|*.png"
        path = unicode(QFileDialog.getSaveFileName(self,
                                                   'Save file', '',
                                                   file_choices))
        if path:
            self.ui.widget.canvas.print_figure(path, dpi=self.dpi)
            self.statusBar().showMessage('Saved to %s' % path, 2000)

    def on_about(self):
        msg = ("Can you read this?  If so, congratulations. You are a magical, "
              + "marvelous troll.")
        QMessageBox.about(self, "About", msg.strip())


def main():
    app = QApplication(sys.argv)
    window = RTBSA()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()