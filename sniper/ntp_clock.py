"""
NTP Time Sync — Relógio de precisão sub-milissegundo.

O SEAP abre login às 06:00:00.000 BRT (09:00:00.000 UTC).
Precisamos sincronizar com servidores NTP para garantir que
disparamos no milissegundo correto, independentemente do clock local.

Estratégia:
  1. Query múltiplos servidores NTP brasileiros
  2. Calcula offset médio (descarta outliers)
  3. Mantém offset calibrado com re-sync periódico
  4. Fornece now_ntp() com precisão ~1-5ms
"""
import asyncio
import socket
import struct
import time
import statistics
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

# NTP servers brasileiros + globais (redundância)
NTP_SERVERS = [
    "a.ntp.br",       # NTP.BR oficial
    "b.ntp.br",       # NTP.BR oficial
    "c.ntp.br",       # NTP.BR oficial
    "pool.ntp.br",    # Pool brasileiro
    "time.google.com",
    "time.cloudflare.com",
]

NTP_PORT = 123
NTP_PACKET_SIZE = 48
NTP_TIMEOUT = 2.0  # segundos

# BRT = UTC-3
BRT = timezone(timedelta(hours=-3))


def _build_ntp_packet() -> bytes:
    """Monta pacote NTP v48 com client transmit timestamp."""
    # Header: LI=0, VN=4, Mode=3 (client), Stratum=0, etc.
    header = 0x1B  # 00011011 = LI=0, VN=4, Mode=3
    packet = bytearray(NTP_PACKET_SIZE)
    packet[0] = header
    # Transmit timestamp starts at byte 40
    # Set client transmit time for round-trip calculation
    tx_time = time.time()
    tx_seconds = int(tx_time) + 2208988800  # NTP epoch offset (1900 vs 1970)
    tx_fraction = int((tx_time - int(tx_time)) * (2**32))
    struct.pack_into("!II", packet, 40, tx_seconds, tx_fraction)
    return bytes(packet)


def _parse_ntp_response(data: bytes) -> dict:
    """Extrai timestamps do pacote NTP de resposta."""
    if len(data) < NTP_PACKET_SIZE:
        raise ValueError("Pacote NTP muito curto")

    # Origin timestamp (T1) - byte 24
    t1_sec, t1_frac = struct.unpack_from("!II", data, 24)
    t1 = t1_sec + t1_frac / (2**32) - 2208988800

    # Receive timestamp (T2) - byte 32
    t2_sec, t2_frac = struct.unpack_from("!II", data, 32)
    t2 = t2_sec + t2_frac / (2**32) - 2208988800

    # Transmit timestamp (T3) - byte 40
    t3_sec, t3_frac = struct.unpack_from("!II", data, 40)
    t3 = t3_sec + t3_frac / (2**32) - 2208988800

    return {"t1": t1, "t2": t2, "t3": t3}


async def query_ntp(server: str, timeout: float = NTP_TIMEOUT) -> Optional[dict]:
    """
    Query um servidor NTP e retorna offset + round-trip delay.

    Returns:
        {"offset": float, "delay": float, "server": str} ou None
    """
    loop = asyncio.get_event_loop()

    def _sync_query():
        t0 = time.time()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(_build_ntp_packet(), (server, NTP_PORT))
            data, _ = sock.recvfrom(NTP_PACKET_SIZE)
            t4 = time.time()
            sock.close()

            ntp = _parse_ntp_response(data)
            # NTP offset calculation:
            # offset = ((T2-T1) + (T3-T4)) / 2
            # delay  = (T4-T1) - (T3-T2)
            offset = ((ntp["t2"] - ntp["t1"]) + (ntp["t3"] - t4)) / 2
            delay = (t4 - t0) - (ntp["t3"] - ntp["t2"])

            return {"offset": offset, "delay": delay, "server": server}
        except Exception as e:
            return None

    result = await loop.run_in_executor(None, _sync_query)
    return result


class NTPClock:
    """
    Relógio sincronizado via NTP.

    Uso:
        clock = NTPClock()
        await clock.sync()
        precise_time = clock.now()         # datetime com offset NTP
        ms = clock.now_ms()                # timestamp ms preciso
        await clock.wait_until(target_dt)  # sleep preciso até horário exato
    """

    def __init__(self):
        self._offset: float = 0.0  # NTP offset em segundos
        self._last_sync: float = 0.0
        self._sync_count: int = 0
        self._sync_interval: float = 300.0  # re-sync a cada 5 min

    @property
    def offset_ms(self) -> float:
        """Offset atual em milissegundos."""
        return self._offset * 1000

    @property
    def last_sync_ago(self) -> float:
        """Segundos desde último sync."""
        return time.time() - self._last_sync

    async def sync(self, samples: int = 3) -> dict:
        """
        Sincroniza com múltiplos servidores NTP.

        Faz 'samples' rounds, coleta offsets, descarta outliers,
        e guarda a mediana como offset calibrado.

        Returns:
            {"offset_ms": float, "samples": int, "servers_used": int}
        """
        all_results = []

        for round_num in range(samples):
            tasks = [query_ntp(server) for server in NTP_SERVERS]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, dict) and r is not None:
                    all_results.append(r)

            if round_num < samples - 1:
                await asyncio.sleep(0.1)

        if not all_results:
            logger.warning("NTP sync falhou — usando clock local (SEM CORREÇÃO)")
            return {"offset_ms": 0, "samples": 0, "servers_used": 0}

        # Filtra resultados com delay < 100ms (conexões boas)
        good_results = [r for r in all_results if r["delay"] < 0.1]
        if not good_results:
            good_results = all_results  # fallback: usa todos

        offsets = [r["offset"] for r in good_results]

        if len(offsets) >= 3:
            # Descarta outliers (desvio > 2σ)
            mean = statistics.mean(offsets)
            stdev = statistics.stdev(offsets)
            offsets = [o for o in offsets if abs(o - mean) <= 2 * stdev]

        self._offset = statistics.median(offsets)
        self._last_sync = time.time()
        self._sync_count += 1

        logger.info(
            f"NTP sync OK: offset={self._offset * 1000:.2f}ms, "
            f"samples={len(good_results)}, "
            f"servers={len(set(r['server'] for r in good_results))}"
        )

        return {
            "offset_ms": round(self._offset * 1000, 2),
            "samples": len(good_results),
            "servers_used": len(set(r["server"] for r in good_results)),
        }

    def now(self) -> datetime:
        """Retorna datetime UTC corrigido pelo offset NTP."""
        corrected = time.time() + self._offset
        return datetime.fromtimestamp(corrected, tz=timezone.utc)

    def now_brt(self) -> datetime:
        """Retorna datetime BRT corrigido pelo offset NTP."""
        return self.now().astimezone(BRT)

    def now_ms(self) -> float:
        """Retorna timestamp em milissegundos (NTP-corrigido)."""
        return (time.time() + self._offset) * 1000

    def now_us(self) -> int:
        """Retorna timestamp em microssegundos (NTP-corrigido)."""
        return int((time.time() + self._offset) * 1_000_000)

    async def wait_until(self, target: datetime, wake_early_ms: float = 50.0) -> None:
        """
        Aguarda até o horário alvo com precisão de milissegundo.

        Estratégia:
        1. Sleep grosso até wake_early_ms antes do alvo (OS-level, eficiente)
        2. Busy-wait os últimos milissegundos (precisão máxima)

        Args:
            target: datetime UTC alvo
            wake_early_ms: Quantos ms antes do alvo sair do sleep grosso
        """
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)

        target_ts = target.timestamp()
        now_ts = time.time() + self._offset
        delta = target_ts - now_ts

        if delta <= 0:
            logger.warning(f"Target já passou: {delta*1000:.0f}ms atrás")
            return

        # Phase 1: Sleep grosso até wake_early_ms antes
        sleep_time = delta - (wake_early_ms / 1000.0)
        if sleep_time > 0:
            logger.info(f"Waiting {sleep_time:.1f}s até {target.astimezone(BRT).strftime('%H:%M:%S.%f')[:-3]} BRT")
            await asyncio.sleep(sleep_time)

        # Phase 2: Busy-wait para precisão máxima
        while True:
            now_ts = time.time() + self._offset
            remaining_us = int((target_ts - now_ts) * 1_000_000)
            if remaining_us <= 0:
                break
            # Yield a cada 100μs para não travar o event loop
            if remaining_us > 200:
                await asyncio.sleep(0)  # yield
            # Últimos 200μs: busy loop puro (prioridade máxima)

        actual_offset_ms = (time.time() + self._offset - target_ts) * 1000
        logger.info(
            f"WAKE! Precisão: {actual_offset_ms:+.1f}ms do alvo "
            f"({target.astimezone(BRT).strftime('%H:%M:%S.%f')[:-3]} BRT)"
        )


# Singleton global
ntp_clock = NTPClock()


def get_thursday_6am_brt() -> datetime:
    """
    Retorna a próxima quinta-feira às 06:00:00.000 BRT (09:00:00.000 UTC).

    Se hoje é quinta e ainda não passou das 6h, retorna hoje.
    """
    now = datetime.now(timezone.utc)

    # Dia da semana: segunda=0, quinta=3
    days_until_thursday = (3 - now.weekday()) % 7
    if days_until_thursday == 0:
        # Hoje é quinta — verifica se já passou das 6h BRT (9h UTC)
        if now.hour >= 9:
            days_until_thursday = 7  # próxima semana

    target = now + timedelta(days=days_until_thursday)
    target = target.replace(hour=9, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    return target


def get_next_thursday_6am_brt() -> datetime:
    """Alias para get_thursday_6am_brt."""
    return get_thursday_6am_brt()
