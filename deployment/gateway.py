"""Generate localhost TLS routing; no external DNS or tunnel is installed."""
import pathlib
ROUTES={8443:'127.0.0.1:18081',8444:'keycloak:8080',8445:'127.0.0.1:18110',8446:'127.0.0.1:18120',8447:'127.0.0.1:18121',8448:'127.0.0.1:18113',8449:'127.0.0.1:18111',8450:'127.0.0.1:18112',8451:'127.0.0.1:18131',8452:'127.0.0.1:18087',8453:'127.0.0.1:18135',8454:'127.0.0.1:18144',8455:'127.0.0.1:18146',8456:'127.0.0.1:18147',8457:'127.0.0.1:18141',8458:'127.0.0.1:18143',8459:'127.0.0.1:18123',8460:'127.0.0.1:18124',8461:'127.0.0.1:18127',8462:'127.0.0.1:18128',8463:'127.0.0.1:18125',8464:'127.0.0.1:18130',8465:'127.0.0.1:18122',8466:'127.0.0.1:18082',8467:'127.0.0.1:18089',8468:'minio:9000',8469:'minio:9001'}
def generate(path):
    text='{\n admin off\n auto_https disable_redirects\n servers {\n protocols h1 h2\n }\n}\n'
    for port,upstream in ROUTES.items():
        text+='https://localhost:'+str(port)+' {\n tls internal\n'
        if port==8443:text+=' handle /auth/* {\n reverse_proxy 127.0.0.1:18117\n }\n handle {\n reverse_proxy '+upstream+'\n }\n'
        elif port==8453:text+=' handle /v1/awe/* {\n reverse_proxy 127.0.0.1:18087\n }\n handle {\n reverse_proxy '+upstream+'\n }\n'
        else:text+=' reverse_proxy '+upstream+'\n'
        text+='}\n'
    pathlib.Path(path).write_text(text)
