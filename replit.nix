{ pkgs }: {
  deps = [
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.python311Packages.flask
    pkgs.python311Packages.pandas
    pkgs.python311Packages.requests
    pkgs.python311Packages.openpyxl
    pkgs.python311Packages.gunicorn
  ];
}
