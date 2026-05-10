"""
Módulo Sniper — Motor de precisão para disputa de vagas SEAP.

Fluxo:
  1. NTP sync → relógio preciso
  2. Pre-warm → browsers abertos, página carregada, credenciais preenchidas
  3. Wait → aguarda exatamente 06:00:00.000 BRT com precisão de ms
  4. FIRE → submit simultâneo de todos os usuários
  5. Loop → busca próxima vaga, preenche, submete, repete até esgotar
"""
