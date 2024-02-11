return {
  -- disable (annoying) mini.indentscope animation
  {
    "echasnovski/mini.indentscope",
    opts = {
      draw = { animation = require("mini.indentscope").gen_animation.none() },
    },
  },
  -- disable (annoying) auto pairing {}, "", ''.
  {
    "echasnovski/mini.pairs",
    enabled = false,
  },
}
