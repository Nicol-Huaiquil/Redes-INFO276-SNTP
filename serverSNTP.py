import datetime
import socket
import struct
import time
import queue
import threading
import select

taskQueue = queue.Queue()
stopFlag = False

def system_to_ntp_time(timestamp):
    return timestamp + NTP.NTP_DELTA    #Traduce el tiempo en formato de sistema al tiempo en formato NTP

def _to_int(timestamp):
    return int(timestamp)               #integral part

def _to_frac(timestamp, n=32):
    return int(abs(timestamp - _to_int(timestamp)) * 2**n)  #fractional part

def _to_time(integ, frac, n=32):
    return integ + float(frac)/2**n	    #32 bits de la parte integral + 32 bits de la parte fraccionaria hacen los 64 bits que se reciben

class NTPException(Exception):
    pass

class NTP:
    _SYSTEM_EPOCH = datetime.date(*time.gmtime(0)[0:3])
    _NTP_EPOCH = datetime.date(1900, 1, 1) #Hora 0
    NTP_DELTA = (_SYSTEM_EPOCH - _NTP_EPOCH).days * 24 * 3600

#Cuando se crea un objeto NTPPacket este adquiere todos los atributos que tiene la clase NTPPacket 
class NTPPacket:
    _PACKET_FORMAT = "!B B B b 11I" #Formato del mensaje del paquete NTP

    def __init__(self, version=3, mode=3, tx_timestamp=0): 
        self.leap = 0               #Leap Indicator: indica el nivel de desface de tiempo del mensaje
        self.version = version      #Version
        self.mode = mode            #Mode
        self.stratum = 0            #Stratum
        self.poll = 0               #Poll interval
        self.precision = 0          #Precision
        self.root_delay = 0         #Root delay
        self.root_dispersion = 0    #Root dispersion
        self.ref_id = 0             #Reference clock identifier
        self.ref_timestamp = 0      #Reference timestamp

        self.orig_timestamp = 0     #Originate Timestamp
        self.orig_timestamp_high = 0#Originate Timestamp Parte entera
        self.orig_timestamp_low = 0 #Originate Timestamp Parte fraccionaria

        self.recv_timestamp = 0     #Receive Timestamp

        self.tx_timestamp = tx_timestamp #Transmit Timestamp
        self.tx_timestamp_high = 0  #Transmit Timestamp Parte entera
        self.tx_timestamp_low = 0   #Transmit Timestamp Parte fraccionaria
        
    #codifica la data en un arreglo de bytes para poder enviarla al cliente
    def to_data(self):
        try:
            packed = struct.pack(NTPPacket._PACKET_FORMAT,
                (self.leap << 6 | self.version << 3 | self.mode),
                self.stratum,
                self.poll,
                self.precision,
                _to_int(self.root_delay) << 16 | _to_frac(self.root_delay, 16),
                _to_int(self.root_dispersion) << 16 | _to_frac(self.root_dispersion, 16),
                self.ref_id,
                _to_int(self.ref_timestamp),
                _to_frac(self.ref_timestamp),
                #Change by lichen, avoid loss of precision
                self.orig_timestamp_high,
                self.orig_timestamp_low,
                
                _to_int(self.recv_timestamp),
                _to_frac(self.recv_timestamp),

                _to_int(self.tx_timestamp),
                _to_frac(self.tx_timestamp))
        except struct.error:
            raise NTPException("Invalid NTP packet fields.")
        return packed   #buffer that can be sent over a socket

    #Decodifica la data de la cola que se recibe desde el cliente
    def from_data(self, data):
        try:
            unpacked = struct.unpack(NTPPacket._PACKET_FORMAT, data[0:struct.calcsize(NTPPacket._PACKET_FORMAT)])
        except struct.error:
            raise NTPException("Invalid NTP packet.")

        self.leap = unpacked[0] >> 6 & 0x3
        self.version = unpacked[0] >> 3 & 0x7
        self.mode = unpacked[0] & 0x7
        self.stratum = unpacked[1]
        self.poll = unpacked[2]
        self.precision = unpacked[3]
        self.root_delay = float(unpacked[4])/2**16
        self.root_dispersion = float(unpacked[5])/2**16
        self.ref_id = unpacked[6]
        self.ref_timestamp = unpacked[7]        #_to_time(unpacked[7], unpacked[8])
        self.orig_timestamp = unpacked[9]       #_to_time(unpacked[9], unpacked[10])
        self.orig_timestamp_high = unpacked[9]  #parte entera
        self.orig_timestamp_low = unpacked[10]  #parte fraccionaria

        self.recv_timestamp = unpacked[11]      #_to_time(unpacked[11], unpacked[12])
        self.tx_timestamp = unpacked[13]        #_to_time(unpacked[13], unpacked[14])
        self.tx_timestamp_high = unpacked[13]   #parte entera
        self.tx_timestamp_low = unpacked[14]    #parte fraccionaria

    def GetTxTimeStamp(self):
        return (self.tx_timestamp_high,self.tx_timestamp_low)

    def SetOriginTimeStamp(self,high,low):
        self.orig_timestamp_high = high
        self.orig_timestamp_low = low
        
class RecvThread(threading.Thread):
    def __init__(self,socket):
        threading.Thread.__init__(self)
        self.socket = socket
    def run(self):
        global taskQueue,stopFlag
        while True:
            if stopFlag == True:
                print("RecvThread Ended")
                break
            rlist,wlist,elist = select.select([self.socket],[],[],1)
            if len(rlist) != 0:
                print("Received %d packets" % len(rlist))
                for tempSocket in rlist:
                    try:
                        data,addr = tempSocket.recvfrom(1024)                               #Espera a que llegue una solicitud
                        recvTimestamp = recvTimestamp = system_to_ntp_time(time.time())     #Hora en la que llega el mensaje
                        taskQueue.put((data,addr,recvTimestamp))                            #Coloca la data en la cola
                    except socket.error:
                        print("msg")

#Prepara el paquete para ser enviado
class WorkThread(threading.Thread):
    def __init__(self,socket):
        threading.Thread.__init__(self)
        self.socket = socket
#
    def run(self):
        global taskQueue,stopFlag
        while True:
            if stopFlag == True:
                print("WorkThread Ended")
                break
            try:
                #Se crea el paquete de recepción
                data,addr,recvTimestamp = taskQueue.get(timeout=1)              #Desde la cola obtiene los datos
                recvPacket = NTPPacket()
                recvPacket.from_data(data)                                      #Decodifica la data de la cola
                timeStamp_high,timeStamp_low = recvPacket.GetTxTimeStamp()      #Parte entera y fraccionaria del tiempo en el que el cliente envió el mensaje
                
                #El servidor crea un nuevo paquete de respuesta
                sendPacket = NTPPacket(version=3,mode=4)                        #Se crea el paquete con versión 3 y mode 4                    
                sendPacket.stratum = 2                                          #Por sercondary reference SNTP
                sendPacket.poll = 10                                            #intervalo máximo entre mensajes sucesivos en segundos 
                sendPacket.ref_timestamp = recvTimestamp-5                      #REF = Hora en la que llegó el mensaje - 5
                sendPacket.SetOriginTimeStamp(timeStamp_high,timeStamp_low)     #ORIGEN = Hora en la que el cliente envió el mensaje
                sendPacket.recv_timestamp = recvTimestamp                       #RECV = Hora en la que llegó el mensaje al servidor
                sendPacket.tx_timestamp = system_to_ntp_time(time.time())       #TX = Hora a la que se envia el mensaje desde el servidor
                
                #Envia el paquete codificado, to_data lo codifica
                socket.sendto(sendPacket.to_data(),addr)
                print("Sended to %s:%d" % (addr[0],addr[1]))
            except queue.Empty:
                continue
                
#listenIp = "127.0.0.1"
listenIp = "192.168.1.108"
listenPort = 123

socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
socket.bind((listenIp,listenPort))
print("local socket: ", socket.getsockname())
recvThread = RecvThread(socket)
recvThread.start()
workThread = WorkThread(socket)
workThread.start()

while True:
    try:
        time.sleep(0.5)
    except KeyboardInterrupt:
        print("Exiting...")
        stopFlag = True
        recvThread.join()
        workThread.join()
        #socket.close()
        print("Exited")
        break