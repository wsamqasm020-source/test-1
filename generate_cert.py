#!/usr/bin/env python
"""توليد شهادة SSL self-signed للشبكة المحلية"""
import ipaddress
import datetime
import subprocess
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def generate_with_cryptography(ip_address):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, 'IQ'),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Attendance System LAN'),
        x509.NameAttribute(NameOID.COMMON_NAME, ip_address),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.ip_address(ip_address)),
            x509.DNSName('localhost'),
            x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
        ]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = os.path.join(SCRIPT_DIR, 'cert.pem')
    key_path = os.path.join(SCRIPT_DIR, 'key.pem')
    with open(cert_path, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, 'wb') as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ))
    return cert_path, key_path

def main():
    import subprocess
    result = subprocess.run(
        ['powershell', '-Command',
         'Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*"} | Select-Object -ExpandProperty IPAddress -First 1'],
        capture_output=True, text=True, timeout=10
    )
    ip = result.stdout.strip().splitlines()[0] if result.stdout.strip() else '192.168.1.100'
    import sys
    # Force UTF-8 output on Windows to avoid UnicodeEncodeError with Arabic text
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print(f'[SSL] Generating certificate for IP: {ip}')
    try:
        cert_path, key_path = generate_with_cryptography(ip)
        print(f'[SSL] OK cert: {cert_path}')
        print(f'[SSL] OK key:  {key_path}')
        agents_tasks_dir = os.path.join(SCRIPT_DIR, '.agents', 'tasks')
        os.makedirs(agents_tasks_dir, exist_ok=True)
        with open(os.path.join(agents_tasks_dir, 'ssl_ip.txt'), 'w') as f:
            f.write(ip)
    except ImportError:
        print('[SSL] ERROR: cryptography package not available. Run: pip install cryptography')
        sys.exit(1)

if __name__ == '__main__':
    main()
