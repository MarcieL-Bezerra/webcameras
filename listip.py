import os
import socket
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

def obter_ip_local():
    """Descobre o IP atual do computador para determinar a faixa da rede."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Não conecta de verdade, serve apenas para descobrir a interface de rede ativa
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def checar_host(ip):
    """Verifica se um IP específico está online enviando um comando Ping."""
    # Parâmetros do ping para o Windows: -n 1 (1 pacote), -w 800 (timeout de 800ms)
    comando = f"ping -n 1 -w 800 {ip} > nul"
    resposta = os.system(comando)
    
    if resposta == 0:
        # Se respondeu ao ping, tenta descobrir o nome do dispositivo (Hostname)
        try:
            nome_dispositivo = socket.gethostbyaddr(ip)[0]
        except socket.herror:
            nome_dispositivo = "Desconhecido"
        
        print(f"[+] ONLINE: {ip:<15} | Nome: {nome_dispositivo}")
        return ip, nome_dispositivo
    return None

def escanear_rede():
    ip_local = obter_ip_local()
    if ip_local == '127.0.0.1':
        print("Erro: Não foi possível detectar sua rede local. Verifique se está conectado.")
        return

    # Extrai os 3 primeiros blocos do IP (ex: "192.168.0.")
    blocos_ip = ip_local.split('.')
    faixa_rede = f"{blocos_ip[0]}.{blocos_ip[1]}.{blocos_ip[2]}."
    
    print("=" * 60)
    print(f"Iniciando varredura na rede: {faixa_rede}0/24")
    print(f"Seu IP local: {ip_local}")
    print("Aguarde, isso levará apenas alguns segundos...")
    print("=" * 60)
    
    # Gera a lista de IPs de 1 a 254
    lista_ips = [f"{faixa_rede}{i}" for i in range(1, 255)]
    
    # Usa ThreadPoolExecutor para testar múltiplos IPs ao mesmo tempo (muito mais rápido)
    with ThreadPoolExecutor(max_workers=50) as executor:
        executor.map(checar_host, lista_ips)

if __name__ == "__main__":
    inicio = datetime.now()
    escanear_rede()
    fim = datetime.now()
    print("=" * 60)
    print(f"Varredura concluída em: {fim - inicio}")
    print("=" * 60)
