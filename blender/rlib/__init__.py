"""Modulos que rodam DENTRO do Blender. Somente bpy e stdlib, sem dependencias.

Toda resolucao de YAML, validacao de schema e versionamento acontece na CLI
de fora (cli/render.py), que entrega um job.json ja resolvido. Assim o lado
Blender e puro executor e o lado de fora e testavel sem abrir o Blender.
"""
