{
  description = "Ansible deployment for a Debian 13 Vultr host";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in {
      devShells = forAllSystems (system:
        let pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.mkShell {
            packages = with pkgs; [
              ansible
              ansible-lint
              yamllint
              sshpass
              python3
            ];
            shellHook = ''
              export ANSIBLE_CONFIG="$PWD/ansible.cfg"
              echo "Ansible development shell ready. Run: ansible-playbook site.yml"
            '';
          };
        });
    };
}
