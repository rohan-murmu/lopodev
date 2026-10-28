# typed: strict
# frozen_string_literal: true

# Formula for the LopoDev game-development workflow toolkit.
class Lopodev < Formula
  desc "Agent workflow toolkit for building mobile games with Blender and Godot"
  homepage "https://github.com/rohan-murmu/lopodev"
  license "MIT"
  head "https://github.com/rohan-murmu/lopodev.git", branch: "main"

  depends_on "python@3.13"

  def install
    libexec.install "AGENTS.md", "README.md", "LICENSE", "VERSION", "opencode.json",
                    "bin", "tools", "templates", "resources", "adapters", "docs"
    # Stable opt/ paths keep workspaces and agent configs valid across upgrades.
    (bin/"lopodev").write <<~SH
      #!/bin/bash
      export LOPODEV_HOME="#{opt_libexec}"
      export LOPODEV_LAUNCHER="#{opt_bin}/lopodev"
      export LOPODEV_BUILD="#{version}"
      exec "#{formula_opt_bin("python@3.13")}/python3.13" "#{opt_libexec}/tools/lopodev_cli.py" "$@"
    SH
  end

  def caveats
    <<~EOS
      Install the pinned Blender MCP, Godot MCP, Code Map and vendored skills
      for your user, then wire LopoDev into a workspace:
        lopodev setup
        lopodev install opencode --project /path/to/workspace
        lopodev doctor --project /path/to/workspace

      Your knowledge base and integrations live in ${XDG_DATA_HOME:-~/.local/share}/lopodev
      and your games live in your workspaces; upgrading or uninstalling
      LopoDev never deletes either.
    EOS
  end

  test do
    assert_match "lopodev", shell_output("#{bin}/lopodev --version")
    assert_match "install", shell_output("#{bin}/lopodev --help")
    ENV["LOPODEV_DATA"] = testpath/"data"
    ENV["LOPODEV_NO_INTEGRATIONS"] = "1"
    assert_match "KNOWLEDGE_VALIDATE=PASS", shell_output("#{bin}/lopodev knowledge validate")
    plan = libexec/"templates/world_plan.json"
    assert_match "WORLD_PLAN_CHECK=PASS", shell_output("#{bin}/lopodev world validate #{plan}")
    system bin/"lopodev", "new", "--workspace", testpath/"ws", "--slug", "brew_test", "--title", "Brew Test"
    assert_path_exists testpath/"ws/projects/brew_test/pipeline_state.json"
    assert_path_exists testpath/"ws/.opencode/agents/lopodev.md"
  end
end
