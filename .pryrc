Y = ->p{->f{f[f]}[->g{p[->*n{g[g][*n]}]}]} unless defined? Y

[ 'prime',
  'fileutils',
  'active_support/time',
  'active_support/core_ext',
  'awesome_print',
  'interactive_editor',
  'term/ansicolor'
].each do |m|
  begin
    require m
  rescue LoadError => e
    warn e
  end
end

if defined? Term::ANSIColor
  class String
    include Term::ANSIColor
  end
end

# vim: set ft=ruby:
