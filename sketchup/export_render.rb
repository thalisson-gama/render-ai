# Exportar para Render - extensao SketchUp para o pipeline render-ai
#
# Instalar:
#   1. SketchUp > Janela > Preferencias > Extensoes > Instalar extensao
#      (ou copiar este arquivo para a pasta Plugins)
#   2. Reiniciar o SketchUp
#   3. Menu Extensoes > Exportar para Render
#
# O que faz, em um clique:
#   - exporta a geometria em GLB (ou DAE, se a versao do SketchUp for antiga)
#   - exporta TODAS as cenas como cameras em cameras.json
#   - lista os materiais do modelo em materials.json, para conferir o contrato
#
# Por que as cameras saem num arquivo separado: nenhum formato de troca
# (GLB, FBX, DAE, OBJ) carrega as Cenas do SketchUp como cameras de forma
# confiavel. A Ruby API carrega, e e o unico caminho que nao quebra.

require 'sketchup.rb'
require 'json'
require 'fileutils'

module M2Black
  module RenderExport
    EXTENSION_NAME = 'Exportar para Render'.freeze

    # SketchUp trabalha em polegadas internamente. Tudo sai em METROS.
    INCH_TO_M = 0.0254

    def self.to_m(point)
      [
        (point.x.to_f * INCH_TO_M).round(5),
        (point.y.to_f * INCH_TO_M).round(5),
        (point.z.to_f * INCH_TO_M).round(5)
      ]
    end

    def self.slugify(name)
      s = name.to_s.strip.downcase
      s = s.tr('áàãâä', 'a').tr('éèêë', 'e').tr('íìîï', 'i')
      s = s.tr('óòõôö', 'o').tr('úùûü', 'u').tr('ç', 'c')
      s = s.gsub(/[^a-z0-9]+/, '-').gsub(/-+/, '-')
      s = s.gsub(/\A-|-\z/, '')
      s.empty? ? 'camera' : s
    end

    def self.collect_cameras(model)
      cameras = []

      model.pages.each do |page|
        cam = page.camera
        next if cam.nil?

        # fov_is_height? diz em qual eixo o SketchUp esta medindo o campo de
        # visao. Assumir sempre vertical (ou sempre horizontal) deixa parte
        # das cenas com enquadramento errado, que e o pior tipo de bug.
        vertical = cam.respond_to?(:fov_is_height?) ? cam.fov_is_height? : true

        entry = {
          'name'     => page.name,
          'slug'     => slugify(page.name),
          'eye'      => to_m(cam.eye),
          'target'   => to_m(cam.target),
          'up'       => [cam.up.x.to_f.round(6), cam.up.y.to_f.round(6), cam.up.z.to_f.round(6)],
          'fov_deg'  => cam.perspective? ? cam.fov.to_f.round(4) : nil,
          'fov_axis' => vertical ? 'vertical' : 'horizontal',
          'perspective' => cam.perspective?
        }

        # Perspectiva de dois pontos: o SketchUp nao expoe isso direto em
        # todas as versoes. Detectamos pelo vetor "up" estar na horizontal,
        # que e a assinatura do modo. Se falhar, da para forcar no
        # project.yaml com cameras.overrides.<slug>.two_point: true
        entry['two_point'] = cam.up.z.to_f.abs < 0.001

        unless cam.perspective?
          entry['ortho_height_m'] = (cam.height.to_f * INCH_TO_M).round(5)
        end

        cameras << entry
      end

      cameras
    end

    def self.collect_materials(model)
      used = Hash.new(0)

      count_entity = lambda do |ent|
        if ent.respond_to?(:material) && ent.material
          used[ent.material.display_name] += 1
        end
      end

      model.entities.each { |e| count_entity.call(e) }
      model.definitions.each do |defn|
        next if defn.image?
        defn.entities.each { |e| count_entity.call(e) }
      end

      model.materials.map do |mat|
        {
          'name'    => mat.display_name,
          'usos'    => used[mat.display_name],
          'cor'     => [mat.color.red, mat.color.green, mat.color.blue],
          'textura' => mat.texture ? File.basename(mat.texture.filename.to_s) : nil
        }
      end.sort_by { |m| -m['usos'] }
    end

    # Versao maior do SketchUp (2022 -> 22). GLB com PBR so existe a partir da 2025.
    def self.major_version
      Sketchup.version.to_s.split('.').first.to_i
    end

    def self.export_geometry(model, dir)
      if major_version >= 25
        glb = File.join(dir, 'modelo.glb')
        begin
          ok = model.export(glb, { :triangulated_faces => true })
          return ['modelo.glb', 'glb'] if ok && File.exist?(glb)
        rescue StandardError => e
          puts "[render-ai] GLB falhou (#{e.message}), caindo para DAE"
        end
      end

      # DAE (Collada) e o melhor formato disponivel antes da 2025: preserva
      # nome de material, UV e hierarquia. As texturas saem numa subpasta.
      dae = File.join(dir, 'modelo.dae')
      options = {
        :triangulated_faces   => true,
        :doublesided_faces    => true,
        :edges                => false,
        :author_attribution   => false,
        :texture_maps         => true,
        :selectionset_only    => false,
        :preserve_instancing  => true
      }
      raise 'falha ao exportar a geometria' unless model.export(dae, options)

      ['modelo.dae', 'dae']
    end

    # Cada Cena tambem sai como PNG. E o unico jeito objetivo de conferir
    # depois se a camera reconstruida no Blender bate com a do SketchUp.
    def self.export_scene_images(model, dir)
      img_dir = File.join(dir, 'cenas_sketchup')
      FileUtils.mkdir_p(img_dir)
      original = model.pages.selected_page
      exportadas = []

      model.pages.each do |page|
        begin
          model.pages.selected_page = page
          path = File.join(img_dir, "#{slugify(page.name)}.png")
          ok = model.active_view.write_image(
            filename: path, width: 1200, height: 800,
            antialias: true, transparent: false
          )
          exportadas << page.name if ok
        rescue StandardError => e
          puts "[render-ai] nao consegui exportar imagem da cena #{page.name}: #{e.message}"
        end
      end

      model.pages.selected_page = original if original
      exportadas
    end

    # Higiene do modelo. Melhor avisar aqui, na hora, do que num documento
    # que ninguem le. Cada item destes some em silencio na exportacao.
    def self.hygiene_report(model)
      avisos = []

      ocultas = model.entities.count { |e| e.respond_to?(:hidden?) && e.hidden? }
      avisos << "#{ocultas} entidades ocultas no modelo (nao vao ser exportadas)" if ocultas > 0

      tags_off = model.layers.reject(&:visible?)
      unless tags_off.empty?
        nomes = tags_off.first(5).map(&:name).join(', ')
        avisos << "#{tags_off.length} tags desligadas (#{nomes}). O que estiver nelas nao sai"
      end

      bbox = model.bounds
      diag_m = bbox.diagonal.to_f * INCH_TO_M
      if diag_m > 200
        avisos << format(
          'o modelo tem %.0f m de diagonal. Provavelmente ha objeto solto longe do projeto',
          diag_m
        )
      end

      sem_cena = model.pages.count.zero?
      avisos << 'nenhuma Cena criada: sem Cena nao ha camera para renderizar' if sem_cena

      avisos
    end

    def self.run
      model = Sketchup.active_model

      if model.path.empty?
        UI.messagebox("Salve o arquivo .skp antes de exportar.")
        return
      end

      if model.pages.count.zero?
        UI.messagebox(
          "Este modelo nao tem nenhuma Cena.\n\n" \
          "Crie as Cenas (Janela > Cenas) com os enquadramentos que voce quer\n" \
          "renderizar. Cada Cena vira uma camera no render."
        )
        return
      end

      default_dir = File.dirname(model.path)
      dir = UI.select_directory(
        title: 'Pasta source/ do projeto no render-ai',
        directory: default_dir
      )
      return if dir.nil?

      FileUtils.mkdir_p(dir)

      begin
        model_file, kind = export_geometry(model, dir)
      rescue StandardError => e
        UI.messagebox("Erro ao exportar a geometria:\n#{e.message}")
        return
      end

      cameras = collect_cameras(model)
      materials = collect_materials(model)
      cenas_png = export_scene_images(model, dir)
      higiene = hygiene_report(model)

      File.write(
        File.join(dir, 'cameras.json'),
        JSON.pretty_generate({
          'gerado_por' => "SketchUp #{Sketchup.version}",
          'modelo'     => File.basename(model.path),
          'unidades'   => 'metros',
          'formato'    => kind,
          'cameras'    => cameras
        })
      )

      File.write(
        File.join(dir, 'materials.json'),
        JSON.pretty_generate({
          'gerado_por' => "SketchUp #{Sketchup.version}",
          'materiais'  => materials
        })
      )

      aviso = higiene.empty? ? '' : "\n\nCONFERIR ANTES DE RENDERIZAR:\n  - " + higiene.join("\n  - ")

      UI.messagebox(
        "Exportado para:\n#{dir}\n\n" \
        "  #{model_file}\n" \
        "  cameras.json      (#{cameras.length} cameras)\n" \
        "  materials.json    (#{materials.length} materiais)\n" \
        "  cenas_sketchup/   (#{cenas_png.length} imagens de referencia)#{aviso}"
      )
    end

    unless file_loaded?(__FILE__)
      menu = UI.menu('Plugins')
      menu.add_item(EXTENSION_NAME) { run }
      file_loaded(__FILE__)
    end
  end
end
