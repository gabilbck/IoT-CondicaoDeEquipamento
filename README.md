# IoT-CondicaoDeEquipamento

Monitoramento da Condição de Equipamentos
1. Integrantes
Gabrieli Eduarda Lembeck
Heloisa Rebello Cabral
Julio Bezerra de Mattos Manoel
Mileine da Silva de Freitas
[Integrante 5]
[Integrante 6]
2. Família temática

Condição de equipamento

O projeto está inserido na temática de monitoramento da condição de equipamentos, utilizando temperatura como principal indicador para identificar possíveis situações de superaquecimento.

3. Problema

Equipamentos eletrônicos como computadores, notebooks e celulares podem apresentar problemas quando sua temperatura ultrapassa níveis considerados adequados. O superaquecimento pode causar perda de desempenho, travamentos e, em situações mais graves, danos aos componentes.

O projeto propõe um sistema simples de monitoramento capaz de verificar a temperatura de diferentes tipos de equipamentos e alertar o usuário quando uma temperatura fora do limite definido for identificada.

4. Usuário e contexto de uso

O sistema será destinado a usuários que desejam acompanhar a condição térmica de equipamentos eletrônicos.

O protótipo poderá representar o monitoramento de diferentes equipamentos, como:

CPU;
Notebook;
Celular.

O usuário poderá selecionar no sistema qual equipamento deseja monitorar. O display apresentará o equipamento selecionado e sua temperatura atual.

5. Objetivo da N1

Desenvolver um protótipo utilizando Arduino capaz de simular o monitoramento da temperatura de diferentes equipamentos, permitindo a seleção do equipamento e apresentando sua temperatura atual em um display.

Quando a temperatura ultrapassar o limite considerado normal para o equipamento selecionado, o sistema deverá emitir um alerta visual e sonoro:

LED piscando;
buzzer emitindo um sinal sonoro.

O objetivo inicial é validar a lógica de monitoramento, identificação de situação normal ou anormal e acionamento dos alertas.

6. Funcionamento previsto

O sistema funcionará da seguinte maneira:

O usuário seleciona o equipamento que deseja monitorar.
O Arduino identifica o equipamento selecionado.
O sensor realiza a leitura da temperatura.
A temperatura atual é apresentada no display.
O sistema compara a temperatura medida com o limite definido para o equipamento.
Caso a temperatura esteja dentro da condição normal, o sistema permanece em estado de monitoramento.
Caso a temperatura ultrapasse o limite estabelecido, o LED começa a piscar e o buzzer é acionado.
Quando a temperatura retornar para uma condição normal, os alertas são desativados.
7. Equipamentos monitorados

Inicialmente serão considerados três equipamentos:

Equipamento	Monitoramento
CPU	Temperatura
Notebook	Temperatura
Celular	Temperatura

Os limites de temperatura serão definidos durante o desenvolvimento do protótipo e poderão ser ajustados conforme os testes realizados.

8. Componentes previstos
Arduino;
Sensor de temperatura;
Display LCD ou similar;
LED;
Buzzer;
Botões para seleção do equipamento;
Resistores;
Protoboard;
Jumpers;
Cabo USB/alimentação.

Os componentes poderão ser ajustados conforme a disponibilidade no laboratório e os testes realizados pela equipe.

9. Arquitetura inicial

A arquitetura inicial será composta por três partes principais:

Entrada:
Botões e sensor de temperatura.

Processamento:
Arduino, responsável por realizar a leitura da temperatura, identificar o equipamento selecionado, comparar a temperatura com o limite definido e controlar os alertas.

Saída:
Display, LED e buzzer.

Fluxo inicial:

        ┌──────────────────┐
        │ Botões de seleção│
        └────────┬─────────┘
                 │
                 ▼
        ┌──────────────────┐
        │     Arduino      │
        │                  │
        │ Leitura do sensor│
        │ Comparação       │
        │ Controle lógico  │
        └───────┬──────────┘
                │
       ┌────────┼─────────┐
       ▼        ▼         ▼
   ┌───────┐ ┌───────┐ ┌────────┐
   │Display│ │  LED  │ │ Buzzer │
   └───────┘ └───────┘ └────────┘
10. Primeiro risco técnico

Risco: dificuldade em obter uma leitura de temperatura adequada para representar diferentes equipamentos utilizando um único sensor.

Como CPU, notebook e celular possuem características diferentes, será necessário definir como o protótipo irá representar a temperatura de cada equipamento e quais limites serão utilizados.

Investigação inicial: testar o sensor disponível no Arduino e verificar sua faixa de medição, precisão e forma de integração com o código.

11. Dúvidas para o professor
Podemos utilizar um único sensor para simular o monitoramento dos três equipamentos?
Os equipamentos precisam possuir limites de temperatura diferentes?
Podemos utilizar valores simulados para representar a temperatura dos equipamentos durante a demonstração?
Qual sensor de temperatura estará disponível no laboratório?
O display LCD pode ser utilizado para apresentar o equipamento selecionado e a temperatura?
12. Estado atual do projeto

O projeto encontra-se na etapa inicial de planejamento. Nesta etapa, a equipe está definindo a arquitetura, os componentes necessários, a lógica de funcionamento e os primeiros testes que serão realizados com o Arduino.

A implementação completa será desenvolvida e validada durante as próximas etapas do projeto.
