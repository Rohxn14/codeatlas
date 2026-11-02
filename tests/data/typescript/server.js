const express = require("express");
const app = express();
const router = express.Router();

function listUsers(req, res) {
  res.json([]);
}

app.get("/api/users", listUsers);
app.post("/api/users/:id", auth, (req, res) => res.sendStatus(201));
router.delete("/items/:itemId?", controller.remove);
router.route("/orders/:id").get(showOrder).put(listUsers);
app.all("/health", (req, res) => res.send("ok"));
app.get("title");
app.use("/v1", router);

module.exports = app;
