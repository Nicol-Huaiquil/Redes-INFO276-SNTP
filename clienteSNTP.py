import socket, struct, sys, time

NTP_SERVER = '192.168.1.108' #Host_Local="127.0.0.1"
Puerto = 9001
TIME1970 = 2208988800

def sntp_client():
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = b'\x1b' + 47 * b'\0'
    client.sendto(data, (NTP_SERVER, Puerto))
    data, address = client.recvfrom(1024)
    if data:
        print('Response received from:', address)
    t = struct.unpack('!12I', data)[10] - TIME1970
    print('\tTime: %s' % time.ctime(t))

if __name__ == '__main__':
    sntp_client()