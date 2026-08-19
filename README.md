# IoT-CondicaoDeEquipamento

# Condição de Equipamento

## Integrantes

* Gabrieli Eduarda Lembeck
* Heloisa Rebello Cabral
* Julio Bezerra de Mattos Manoel
* Mileine da Silva de Freitas
* Thomas Henry Steinback

## Família temática

**Internet das Coisas (IoT) — Monitoramento de condições de equipamentos.**

## Problema

Equipamentos eletrônicos, como computadores, notebooks e celulares, podem apresentar problemas relacionados ao aumento excessivo de temperatura. Quando a temperatura ultrapassa um determinado limite, o usuário pode não perceber imediatamente, o que pode causar perda de desempenho, desligamentos ou possíveis danos ao equipamento.

O projeto busca desenvolver uma solução simples de monitoramento capaz de identificar quando a temperatura de um equipamento está fora da faixa considerada normal e alertar o usuário.

## Usuário e contexto de uso

O sistema será destinado a usuários que desejam acompanhar a temperatura de diferentes equipamentos eletrônicos.

O protótipo poderá representar três tipos de equipamentos:

* CPU/computador;
* Notebook;
* Celular.

O usuário poderá selecionar o equipamento que deseja monitorar. O sistema exibirá a temperatura atual no display e verificará se ela está dentro da condição considerada normal.

## Objetivo da N1

Desenvolver um protótipo com Arduino capaz de monitorar a temperatura de diferentes equipamentos, apresentar a temperatura atual em um display e emitir um alerta visual e sonoro quando a temperatura estiver acima do limite definido.

O sistema deverá:

1. Permitir a seleção do equipamento a ser monitorado.
2. Medir ou simular a temperatura do equipamento selecionado.
3. Exibir a temperatura atual no display.
4. Comparar a temperatura medida com um limite definido.
5. Identificar uma condição de temperatura fora do normal.
6. Acionar um LED piscante quando houver uma condição de alerta.
7. Emitir um sinal sonoro por meio de um buzzer quando houver uma condição de alerta.

## Funcionamento inicial

O usuário selecionará no sistema qual equipamento deseja monitorar.

Após a seleção, o Arduino apresentará no display o equipamento escolhido e sua temperatura atual.

A temperatura será comparada com um limite definido para aquele equipamento. Enquanto a temperatura estiver dentro da faixa normal, o sistema permanecerá em estado normal.

Caso a temperatura ultrapasse o limite estabelecido, o sistema entrará em estado de alerta, fazendo com que:

* o LED comece a piscar;
* o buzzer emita um sinal sonoro;
* o display informe que a temperatura está fora do normal.

### Exemplo

**Equipamento:** Notebook
**Temperatura:** 65 °C
**Estado:** Normal

Caso a temperatura ultrapasse o limite:

**Equipamento:** Notebook
**Temperatura:** 90 °C
**Estado:** ALERTA
**LED:** Piscando
**Buzzer:** Ligado

## Componentes previstos

* Arduino;
* Sensor de temperatura;
* Display LCD ou OLED;
* LED;
* Buzzer;
* Botões para seleção do equipamento;
* Resistores;
* Protoboard;
* Jumpers;
* Cabo USB;
* Computador para programação e testes.

A definição exata dos componentes poderá ser ajustada durante os testes em laboratório.

## Arquitetura inicial

O sistema terá o Arduino como unidade central de processamento.

```text
Usuário
   |
   v
Botões
   |
   v
Arduino <---- Sensor de temperatura
   |
   +----> Display
   |
   +----> LED
   |
   +----> Buzzer
```

O Arduino será responsável por receber a seleção do equipamento, obter a temperatura, comparar o valor com o limite definido e controlar os dispositivos de saída.

## Backlog inicial

| ID | Tarefa                                             | 
| -- | -------------------------------------------------- | 
| 01 | Criar repositório do projeto                       |
| 02 | Criar e preencher o README inicial                 | 
| 03 | Identificar o sensor de temperatura disponível     |
| 04 | Testar a leitura do sensor no Arduino              |
| 05 | Testar o funcionamento do display                  | 
| 06 | Exibir uma temperatura no display                  |
| 07 | Testar botão de seleção                            |
| 08 | Definir os equipamentos disponíveis para seleção   | 
| 09 | Definir os limites de temperatura dos equipamentos |
| 10 | Testar o LED piscante                              |
| 11 | Testar o buzzer                                    |
| 12 | Implementar comparação da temperatura com o limite |
| 13 | Implementar alerta visual de temperatura           |
| 14 | Implementar alerta sonoro de temperatura           |
| 15 | Integrar seleção, sensor, display e alertas        |
| 16 | Realizar teste completo do protótipo               |
| 17 | Registrar resultados e problemas encontrados       | 

## Primeiro risco técnico

**Risco:** o sensor de temperatura disponível pode não representar adequadamente a temperatura real de diferentes equipamentos, principalmente porque o projeto pretende representar CPU, notebook e celular.

**Impacto:** as temperaturas medidas podem não corresponder às temperaturas reais dos equipamentos, dificultando a validação dos limites.

**Investigação:** testar o sensor disponível no laboratório e verificar se ele consegue fornecer leituras estáveis. Caso necessário, utilizar diferentes valores de referência para representar os equipamentos durante o protótipo.

## Dúvidas para o professor

* Podemos utilizar um único sensor para representar os diferentes equipamentos?
* Os equipamentos podem ser representados por valores de temperatura simulados durante a demonstração?
* Podemos definir limites de temperatura diferentes para CPU, notebook e celular?
* Qual modelo de display e sensor de temperatura é recomendado para o projeto?
* A seleção dos equipamentos pode ser realizada por botões físicos?

## Estado atual

O projeto está em fase inicial de planejamento. Nesta etapa, o objetivo é definir a ideia, os componentes, a arquitetura inicial, os primeiros testes e as tarefas necessárias para desenvolver o protótipo.
