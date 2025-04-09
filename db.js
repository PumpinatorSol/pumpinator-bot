require('dotenv').config();
const { MongoClient } = require('mongodb');

console.log("📡 MONGO_URI from db.js:", process.env.MONGO_URI);

const client = new MongoClient(process.env.MONGO_URI);
let db;

async function connectDB() {
  await client.connect();
  db = client.db('pumpinator');
  console.log("🧠 Connected to MongoDB!");
}

function getDB() {
  return db;
}

module.exports = { connectDB, getDB };
