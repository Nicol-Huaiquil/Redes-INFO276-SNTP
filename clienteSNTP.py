import socket, struct, time
SNTP_SERVER = '192.168.1.108' #"127.0.0.1" #Local
Puerto = 123
TIME1970 = 2208988800 #Diferencia de 1900 NTP timestamps - 1970 UTC (2208988800 - 0)
def sntp_client():
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = b'\x1b' + 47 * b'\0' #1 byte = 8 bits 00 011 011 (LI,VN,Mode) + 47 bytes = 376 bits
    client.sendto(data, (SNTP_SERVER, Puerto))
    data, address = client.recvfrom(1024)
    if data:
        print('Response received from:', address)
    t = struct.unpack('!12I', data)[10] - TIME1970 #Tiempo Actual NTP - Time1970 -> UTC
    print('\tTime: %s' % time.ctime(t))

if __name__ == '__main__':
    sntp_client()

