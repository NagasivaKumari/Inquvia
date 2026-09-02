import fs from "fs";
import path from "path";
import dbConnect from "../src/lib/db/mongodb";
import { User } from "../src/lib/db/models/user";
import { Investigation } from "../src/lib/db/models/investigation";
import { Payment } from "../src/lib/db/models/payment";
import { Session } from "../src/lib/db/models/session";
import { Reset } from "../src/lib/db/models/reset";

async function migrate() {
  const dbPath = path.join(process.cwd(), "data", "inquvia.json");
  if (!fs.existsSync(dbPath)) {
    console.error("Legacy database file not found at", dbPath);
    return;
  }

  console.log("Connecting to MongoDB...");
  await dbConnect();
  console.log("Connected.");

  const raw = fs.readFileSync(dbPath, "utf-8");
  const data = JSON.parse(raw);

  console.log("Migrating users...");
  await User.insertMany(data.users.map((u: any) => ({
    _id: new (require("mongoose").Types.ObjectId)(u.id.replace("usr_", "").padEnd(24, "0")),
    ...u,
    id: undefined
  })));

  console.log("Migrating investigations...");
  await Investigation.insertMany(data.investigations.map((i: any) => ({
    ...i,
    userId: new (require("mongoose").Types.ObjectId)(i.userId.replace("usr_", "").padEnd(24, "0")),
    id: undefined
  })));

  console.log("Migration complete.");
  process.exit(0);
}

migrate().catch(console.error);
