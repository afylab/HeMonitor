import sys
from PyQt5 import QtWidgets
from LevelMonitorGUI import LevelMonitorGUI

params = {
'active length':29.53,
'belly bottom level':8.27,
'belly top level':26.58,
'belly L per in':3.84,
'tail L per in':0.6,
'fill level':8.27,
'default interval':'05:00:00',
'fillmode interval':'00:01:00',
'nanosquid system':'1p5K',
'pass file':"C:\\Users\\Cthulhu\\Software\\password.txt",
'SQL Database':"Squid1p5K",
}

""" The following runs the GUI"""
if __name__ == "__main__":
    import qt5reactor
    app = QtWidgets.QApplication(sys.argv)

    qt5reactor.install()
    from twisted.internet import reactor
    window = LevelMonitorGUI(reactor, params)
    window.show()
    # try:
    #     window = LevelMonitorGUI(reactor, params)
    #     window.show()
    # except:
    #     from traceback import format_exc
    #     print("-------------------")
    #     print("Main loop crashed")
    #     print(format_exc())
    #     print("-------------------")

    reactor.runReturn()
    sys.exit(app.exec_())
