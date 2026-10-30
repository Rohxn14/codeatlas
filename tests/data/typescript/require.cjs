const express = require("express");
const { join, resolve: resolvePath } = require("path");
require("dotenv/config");
const notLiteral = require(name);

function load() {
  return join("a", "b");
}

module.exports = { load };
