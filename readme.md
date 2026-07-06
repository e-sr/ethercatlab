# ethercat_lab

Libreria Python e REPL interattivo per il controllo e il debug di bus EtherCAT su banco prova Beckhoff.

Il progetto espone un wrapper su [pysoem](https://github.com/bnjmorgan/pysoem) con supporto CoE/AoE, mapping PDO tipizzato e driver per terminali EL6224 (IO-Link) ed EL3072 (ingressi analogici), più descrittori IO-Link per sensori industriali.

## Requisiti

- Python 3.13
- [PDM](https://pdm-project.org/) per la gestione delle dipendenze
- [pysoem](https://github.com/bnjmorgan/pysoem) — installato come dipendenza di sviluppo dal repo sibling `../pysoem`
- Interfaccia di rete EtherCAT (es. `enp2s0`) con master IgH o stack compatibile
- Permessi sufficienti per aprire l'interfaccia raw (spesso `sudo` o capability `CAP_NET_RAW`)

## Installazione

```bash
git clone <repo-url> ethercatlab
cd ethercatlab
pdm install
```

Assicurati che il checkout di `pysoem` sia disponibile in `../pysoem` rispetto alla root del progetto, oppure aggiorna il path in `pyproject.toml` sotto `[tool.pdm.dev-dependencies]`.

## Avvio rapido

Apri una sessione IPython con il bus già inizializzato:

```bash
pdm run eci <ifname>
```

Esempio con modulo di macro personalizzato (vedi `example/`):

```bash
pdm run eci enp2s0 --macros example/func.py --merge-macros-ns
```

All'avvio il REPL:

1. apre il master sull'interfaccia indicata;
2. esegue `config_init` e resta in INIT (transizioni manuali);
3. elenca gli slave con `%ec_slaves`.

La variabile `bus` (istanza di `Master`) è disponibile nel namespace REPL.

## Comandi IPython (%magic)

| Comando | Descrizione |
|---------|-------------|
| `%ec_slaves [N]` | Elenca gli slave o mostra i dettagli dello slave `N` (indice 1-based, come pysoem) |
| `%ec_coe S [IDX]` | Object Dictionary CoE dello slave `S`, oppure singolo oggetto `0xIDX` |
| `%ec_coe_read S IDX [SUB] [--all] [--encoded]` | Lettura CoE con decode via OD (default) o hex grezzo |
| `%ec_coe_write S IDX SUB VALUE [--encoded]` | Scrittura CoE tipizzata o hex grezzo |
| `%ec_aoe_init S [SNET]` | Inizializza routing AoE/AMS (legge netid da CoE `0x0920` se omesso) |
| `%ec_aoe_read S IG OFF SIZE PORT` | Lettura AoE |
| `%ec_aoe_write S IG OFF PORT HEX` | Scrittura AoE |
| `%ec_reinit` | Chiude e riapre il master |

Valori numerici accettano notazione decimale o esadecimale (`0x1A00`).

## Struttura del progetto

```
src/
├── ethercat_lab/
│   ├── master.py          # Master EtherCAT: stati AL, CoE, AoE, ciclo PDO
│   ├── coe.py             # Tipi e decode/pack CoE (bitstruct)
│   ├── aoe.py             # Costanti e helper AoE/AMS
│   ├── pdo.py             # Mapping e assegnazione PDO
│   ├── beckhoff_device.py # Base class terminali Beckhoff
│   ├── el6224.py          # EL6224 IO-Link master
│   ├── el3072.py          # EL3072 ingressi analogici 2ch
│   ├── magics.py          # Magic IPython (%ec_*)
│   └── cli.py             # Entry point `eci`
└── iolink_sensors/
    ├── descriptors/       # YAML descrittori sensori (PF2M7, PSD4, …)
    ├── loader.py          # Caricamento e merge descrittori
    ├── pf2m7.py           # Sensore flusso SMC PF2M7
    └── psd4.py            # Sensore pressione IFM PSD4

example/
├── func.py                # Esempio banco prova (EL1004, EL6224, EL2004, EL3072)
└── runeci.sh              # Script di avvio con sudo

tests/                     # Test offline (+ hw opzionali)
doc/                       # Documentazione hardware e datasheet
```

## API principale

### Master

```python
from ethercat_lab import Master

bus = Master("enp2s0")
bus.open(manual_state_change=True)

bus.to_preop(lambda: ...)   # hook PRE-OP (config CoE, AoE init)
bus.to_safeop()             # config_map + transizione SAFE-OP
bus.to_op()

bus.cycle()                 # send/receive process data
raw_in = bus.pdoin(slave_idx)
bus.pdoout_set(slave_idx, payload)

bus.read_coe(slave_idx, 0x1C12, 0)
bus.write_coe(slave_idx, index, subindex, b"...")

bus.close()
```

### Terminali Beckhoff

```python
from ethercat_lab import EL6224, EL3072, IoLinkChannelConfig
from iolink_sensors.pf2m7 import Pf2m7Device

iolink = EL6224(bus, slave_idx=3)
iolink.set_channel(IoLinkChannelConfig(port=1, pd_in=Pf2m7Device().pd_in_layout))
iolink.configure_preop(aoe_init=True)

ai = EL3072(bus, slave_idx=5)
ai.set_channel(...)         # AnalogInputChannel con scala, filtri, limiti
ai.configure_preop()
```

I terminali generano le scritture CoE necessarie (`coe_setup_writes`), costruiscono le assegnazioni PDO e decodificano i frame di process data.

### Sensori IO-Link

I descrittori YAML in `iolink_sensors/descriptors/` definiscono layout PDO, registri ISDU e comandi di sistema. I device (`Pf2m7Device`, `Psd4Device`) espongono `sample(**pd_fields)` per convertire i byte PDO in valori fisici.

## Esempio banco prova

Il modulo `example/func.py` configura un banco con:

| Slave | Terminale | Ruolo |
|-------|-----------|-------|
| 2 | EL1004 | Ingressi digitali |
| 3 | EL6224 | Master IO-Link (PF2M7 su porta 1) |
| 4 | EL2004 | Uscite digitali |
| 5 | EL3072 | AI: CH1 4–20 mA, CH2 0–10 V |

Dopo `--merge-macros-ns` sono disponibili `banco`, `blink_and_print()`, `exchange_pdo_op()` e altre helper.

```bash
cd example
sudo ../.venv/bin/pdm run eci enp2s0 --macros func.py --merge-macros-ns
```

In REPL:

```python
banco.read_pdo_safeop()
blink_and_print(banco, sample_period=0.1)
```

## Test

Test offline (senza hardware):

```bash
pdm run pytest tests/ -v --ignore=tests/test_hw_ethercat.py
```

I test hardware richiedono un bus reale e la variabile `ETHERCAT_IFACE`:

```bash
ETHERCAT_IFACE=enp2s0 pdm run pytest tests/test_hw_ethercat.py -v
```

> **Nota:** `tests/test_hw_ethercat.py` fa ancora riferimento al vecchio modulo `banco_prova` ed è da aggiornare.

## Transizioni di stato

Il master implementa le transizioni AL EtherCAT con azioni di entry/exit PRE-OP:

```
INIT → PRE-OP → SAFE-OP → OP
         ↑ config CoE/AoE
              ↑ config_map (PDO)
                   ↑ cycle() prima di OP
```

Per AoE/ISDU su EL6224 serve almeno SAFE-OP; l'inizializzazione AMS (`aoe_init`) va fatta in PRE-OP tramite `configure_preop()`.

## Licenza

MIT — vedi `pyproject.toml`.
