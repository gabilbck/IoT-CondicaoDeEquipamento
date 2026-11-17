# Mapa de pinos e ligações (CP12 §5)

Os mesmos pinos estão definidos no topo de `firmware/sonda/sonda.ino` e `firmware/controlador/controlador.ino`.
Esquemas elétricos completos no PDF do CP12 (seção 5).

## Resumo

| Dispositivo | GPIO | Função | Nível |
|---|---|---|---|
| `sonda-01` | 35 | pH (ADC1_CH7), Po do PH-4502C pelo divisor 10k/10k | máx. 2,5 V no pino |
| `sonda-01` | 4 | DS18B20 (1-Wire), pull-up 4,7 kΩ para 3V3 | 3,3 V |
| `sonda-01` | 21 / 22 | OLED SSD1306 SDA / SCL (I²C 0x3C) | 3,3 V |
| `sonda-01` | 25 | Buzzer via BC547 (base com 1 kΩ) | HIGH = toca |
| `ctrl-01` | 25 | Bomba pH+ via IRLZ44N (gate 220 Ω, pull-down 10 kΩ) | HIGH = liga |
| `ctrl-01` | 26 | Bomba pH− via IRLZ44N (gate 220 Ω, pull-down 10 kΩ) | HIGH = liga |
| `ctrl-01` | 32 | IN1 do módulo relé → aquecedor no contato **NC** (pull-up 10 kΩ) | LOW = relé energizado = aquecedor **bloqueado** |
| `ctrl-01` | 33 | IN2 do módulo relé → cooler no contato **NO** (pull-up 10 kΩ) | LOW = relé energizado = cooler **ligado** |
| `ctrl-01` | 34 | Boia de nível (só entrada), pull-up externo 10 kΩ + 100 nF | LOW = boia fechada = nível OK |

Nenhum GPIO 6–11 e nenhum atuador em pino de strapping (0, 2, 5, 12, 15). O LED do GPIO2 deixa de ser atuador.

## Ligações ponto a ponto — Sonda (`sonda-01`)

| De | Para |
|---|---|
| PH-4502C V+ | +5 V |
| PH-4502C G | GND |
| PH-4502C Po | R1 10 kΩ → nó do divisor → GPIO35; nó → R2 10 kΩ → GND |
| PH-4502C Do, To | não ligar |
| DS18B20 vermelho (VDD) | 3V3 |
| DS18B20 amarelo (DQ) | GPIO4 **e** R3 4,7 kΩ → 3V3 |
| DS18B20 preto (GND) | GND |
| OLED VCC / GND / SDA / SCL | 3V3 / GND / GPIO21 / GPIO22 |
| GPIO25 | R4 1 kΩ → base do BC547 |
| BC547 emissor | GND |
| BC547 coletor | − do buzzer; + do buzzer em +5 V; D1 1N4148 em antiparalelo com o buzzer (catodo no +5 V) |
| VIN / GND da placa | +5 V / GND do LM2596, com C1 100 µF + C2 100 nF junto ao VIN |

## Ligações ponto a ponto — Controlador (`ctrl-01`) + alimentação

| De | Para |
|---|---|
| Fonte 12 V (+) | F1 3 A → trilho +12 V (C3 470 µF/25 V entre +12 V e GND) → IN+ do LM2596 |
| Fonte 12 V (0 V) | IN− do LM2596 = **ponto de terra em estrela** |
| LM2596 OUT+ | trilho +5 V (**ajustar para 5,0 V com multímetro antes de ligar as placas**) |
| +5 V / GND | VIN / GND das duas ESP32 (C4 100 µF + C5 100 nF junto ao VIN), JD-VCC do módulo relé |
| GPIO25 | R6 220 Ω → gate Q2 (IRLZ44N); gate → R7 10 kΩ → GND |
| Q2 dreno | − da bomba pH+; + da bomba no +12 V; D2 1N5819 em antiparalelo (catodo no +12 V) |
| Q2 source | GND (fio direto à estrela) |
| GPIO26 | R8 220 Ω → gate Q3; gate → R9 10 kΩ → GND |
| Q3 dreno / source | bomba pH− com D3 1N5819, igual à pH+ |
| Módulo relé VCC (entradas) | **3V3** (jumper JD-VCC removido) |
| Módulo relé JD-VCC / GND | +5 V / GND |
| GPIO32 | IN1 e R10 10 kΩ → 3V3 |
| GPIO33 | IN2 e R11 10 kΩ → 3V3 |
| K1 (aquecedor, 220/127 V) | FASE → F2 1 A → K1 COM; K1 **NC** → aquecedor; neutro direto ao aquecedor |
| K2 (cooler, 12 V) | +12 V → K2 COM; K2 **NO** → + do cooler; − do cooler → GND; D4 1N5819 em antiparalelo |
| Boia S1 | um fio no GPIO34, outro no GND; GPIO34 → R5 10 kΩ → 3V3; C6 100 nF do GPIO34 ao GND |

> Nos testes de bancada o aquecedor 220 V é trocado por uma carga de 12 V (lâmpada/LED com resistor). A rede só
> entra com a caixa fechada, bornes parafusados e montagem conferida por mais de um integrante.

## Estado no boot (sem firmware rodando)

| Saída | Garantido por | Resultado |
|---|---|---|
| Bombas | R7/R9 puxam o gate para 0 V | desligadas |
| Cooler | R11 mantém IN2 em 3,3 V (módulo ativo em LOW) | relé solto → NO aberto → desligado |
| Aquecedor | R10 mantém IN1 em 3,3 V | relé solto → NC fechado → aquecedor no termostato próprio |
| Buzzer | base do BC547 sem corrente | mudo |
