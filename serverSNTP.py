import datetime, socket, struct, time, queue, threading, select

taskQueue = queue.Queue()   #cola para guardar paquetes
stopFlag = False    #Para parar el servidor

class NTP:
    _SYSTEM_EPOCH = datetime.date(*time.gmtime(0)[0:3]) #Hora 0 1970 UTC
    _NTP_EPOCH = datetime.date(1900, 1, 1) #Hora NTP
    NTP_DELTA = (_SYSTEM_EPOCH - _NTP_EPOCH).days * 24 * 3600   #Tiempo en formato NTP

#Traduce el tiempo en formato de sistema al tiempo en formato NTP
def system_to_ntp_time(timestamp):
    return timestamp + NTP.NTP_DELTA    

#Parte entera de un tiempo NTP
def _to_int(timestamp):
    return int(timestamp)               

#Parte fraccional de un tiempo NTP
def _to_frac(timestamp, n=32):
    return int(abs(timestamp - _to_int(timestamp)) * 2**n)  

#Une parte entera con fraccionaria para tener el tiempo en NTP
def _to_time(integ, frac, n=32):
    return integ + float(frac)/2**n

#Para paquetes con formato distinto a NTP
class NTPException(Exception):
    pass

class NTPPacket:
    _PACKET_FORMAT = "!B B B b 11I" #Formato del mensaje del paquete NTP B,b = 1 Bytes; I = 4 Bytes

    #Creación de base de paquetes (Recepción, Respuesta)
    def __init__(self, version=3, mode=3, tx_timestamp=0): 
        self.leap = 0               #Leap Indicator: indica el nivel de desface de tiempo del mensaje
        self.version = version      #Version
        self.mode = mode            #Mode
        self.stratum = 3            #Stratum por reloj
        self.poll = 0               #Poll interval
        self.precision = 0          #Precision  por reloj
        self.root_delay = 0         #Root delay
        self.root_dispersion = 0    #Root dispersion
        self.ref_id = 0             #Reference clock identifier por reloj
        self.ref_timestamp = 0      #Reference timestamp
        self.orig_timestamp = 0     #Originate Timestamp
        self.orig_timestamp_high = 0#Originate Timestamp Parte entera
        self.orig_timestamp_low = 0 #Originate Timestamp Parte fraccionaria
        self.recv_timestamp = 0     #Receive Timestamp
        self.tx_timestamp = tx_timestamp #Transmit Timestamp
        self.tx_timestamp_high = 0 #Transmit Timestamp parte entera
        self.tx_timestamp_low = 0 #Transmit Timestamp parte fraccionaria
        
    #codifica el paquete de respuesta en un arreglo de bytes para poder enviarla al cliente
    def to_data(self):
        try:
            #Arreglo de bytes
            packed = struct.pack(
                NTPPacket._PACKET_FORMAT, #Formato del arreglo
                #Items que completan el arreglo
                (self.leap << 6 | self.version << 3 | self.mode),   #00 000 000
                self.stratum,
                self.poll,
                self.precision,
                _to_int(self.root_delay) << 16 | _to_frac(self.root_delay, 16),
                _to_int(self.root_dispersion) << 16 | _to_frac(self.root_dispersion, 16),
                self.ref_id,
                _to_int(self.ref_timestamp),
                _to_frac(self.ref_timestamp),
                self.orig_timestamp_high,
                self.orig_timestamp_low,
                _to_int(self.recv_timestamp),
                _to_frac(self.recv_timestamp),
                _to_int(self.tx_timestamp),
                _to_frac(self.tx_timestamp)
                )
        except struct.error:
            raise NTPException("Invalid NTP packet fields.")
        return packed

    #Decodifica la data del cliente para llenar el paquete de recepción
    def from_data(self, data):
        try:
            #Lista de 15 elementos 
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
        self.ref_timestamp = _to_time(unpacked[7], unpacked[8])
        self.orig_timestamp = _to_time(unpacked[9], unpacked[10])
        self.orig_timestamp_high = unpacked[9]  #parte entera
        self.orig_timestamp_low = unpacked[10]  #parte fraccionaria
        self.recv_timestamp = _to_time(unpacked[11], unpacked[12])
        self.tx_timestamp = _to_time(unpacked[13], unpacked[14])
        self.tx_timestamp_high = unpacked[13]   #parte entera
        self.tx_timestamp_low = unpacked[14]    #parte fraccionaria

    def GetTxTimeStamp(self):
        return (self.tx_timestamp_high, self.tx_timestamp_low)

    def SetOriginTimeStamp(self,high,low):
        self.orig_timestamp_high = high #Parte entera
        self.orig_timestamp_low = low   #Parte fraccionaria
        
#Para enviar y recibir paquetes        
class RecvThread(threading.Thread):
    def __init__(self,socket):
        threading.Thread.__init__(self) #Se inicia un hilo para la clase
        self.socket = socket #Para guardar el socket inicializado
    def run(self):
        global taskQueue,stopFlag
        while True:
            if stopFlag == True:       #Cierra los hilos
                print("RecvThread Ended")
                break
            rlist,wlist,elist = select.select([self.socket],[],[],1)
            if len(rlist) != 0:   #Verifica si el socket tiene algo
                print("Received %d packets" % len(rlist))
                for tempSocket in rlist:
                    try:
                        data,addr = tempSocket.recvfrom(1024)                               #Espera a que llegue una solicitud
                        recvTimestamp = recvTimestamp = system_to_ntp_time(time.time())     #Hora en la que llega el mensaje
                        taskQueue.put((data,addr,recvTimestamp))                            #Coloca la data en la cola
                    except socket.error:
                        print("msg")

#Prepara el paquete y lo envía al cliente
class WorkThread(threading.Thread):
    def __init__(self,socket):
        threading.Thread.__init__(self) #Se inicia un hilo para la clase
        self.socket = socket #Para guardar el socket inicializado 

    def run(self):
        global taskQueue,stopFlag
        while True:
            if stopFlag == True:
                print("WorkThread Ended")   #Para cerrar los hilos
                break
            try:
                #Se crea el paquete de recepción
                data,addr,recvTimestamp = taskQueue.get(timeout=1)              #Desde la cola obtiene los datos
                recvPacket = NTPPacket()                                        #Crea un objeto NTPPacket
                recvPacket.from_data(data)                                      #Objeto con data de cliente
                timeStamp_high,timeStamp_low = recvPacket.GetTxTimeStamp()      #Parte entera y fraccionaria del tiempo en el que el 
                                                                                #cliente envió el mensaje
                #El servidor crea un nuevo paquete de respuestas
                sendPacket = NTPPacket(version=4,mode=4)                        #Se crea el objeto NTPPacket con versión 3 y mode 4          
                sendPacket.stratum = 2                                          #Por sercondary reference SNTP
                sendPacket.poll = recvPacket.poll                               #Intervalo máximo entre mensajes sucesivos en segundos 
                sendPacket.ref_timestamp = recvTimestamp-5                      #REF = fecha en la que llegó el mensaje - 5
                sendPacket.SetOriginTimeStamp(timeStamp_high,timeStamp_low)     #ORIGEN = fecha en la que el cliente envió el mensaje
                sendPacket.recv_timestamp = recvTimestamp                       #RECV = fecha en la que llegó el mensaje al servidor
                sendPacket.tx_timestamp = system_to_ntp_time(time.time())       #TX = fecha a la que se envia el mensaje desde el servidor
                #Envia el paquete codificado, to_data lo codifica
                socket.sendto(sendPacket.to_data(),addr)
                print("Sended to %s:%d" % (addr[0],addr[1]))
            except queue.Empty:                                                 #Si la cola está vacía
                continue
                
#listenIp = "127.0.0.1"
listenIp = "192.168.1.108"
listenPort = 123

socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)    #Creación de socket
socket.bind((listenIp,listenPort))                          #Inicializa el socket
print("local socket: ", socket.getsockname())
recvThread = RecvThread(socket)                             #Creación del objeto
recvThread.start()                                          #Inicializa un hilo
workThread = WorkThread(socket)                             #Creación del objeto
workThread.start()                                          #Inicializa un hilo

while True:
    try:
        time.sleep(0.5)
    except KeyboardInterrupt:
        print("Exiting...")
        stopFlag = True
        recvThread.join()
        workThread.join()
        print("Exited")
        break