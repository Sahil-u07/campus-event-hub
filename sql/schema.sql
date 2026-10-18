-- MySQL version of the Campus Event Hub tables.
-- You do not need to run this by hand: `python manage.py migrate` creates the
-- same tables. It is here to show the structure and the basic CRUD queries.
-- (auth_user is created by Django's built-in auth app.)

CREATE DATABASE IF NOT EXISTS campushub CHARACTER SET utf8mb4;
USE campushub;

CREATE TABLE events_category (
  id   BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE events_event (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  title        VARCHAR(120) NOT NULL,
  description  LONGTEXT NOT NULL,
  venue        VARCHAR(120) NOT NULL,
  start_at     DATETIME(6) NOT NULL,
  capacity     INT UNSIGNED NOT NULL,
  created_at   DATETIME(6) NOT NULL,
  category_id  BIGINT NOT NULL,
  organiser_id INT NOT NULL,
  FOREIGN KEY (category_id)  REFERENCES events_category (id),
  FOREIGN KEY (organiser_id) REFERENCES auth_user (id) ON DELETE CASCADE
);

CREATE TABLE events_registration (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  created_at DATETIME(6) NOT NULL,
  event_id   BIGINT NOT NULL,
  user_id    INT NOT NULL,
  CONSTRAINT one_seat_per_user UNIQUE (event_id, user_id),
  FOREIGN KEY (event_id) REFERENCES events_event (id) ON DELETE CASCADE,
  FOREIGN KEY (user_id)  REFERENCES auth_user (id) ON DELETE CASCADE
);

-- CRUD examples ------------------------------------------------------------

-- Create
INSERT INTO events_category (name) VALUES ('Tech');

-- Read: upcoming events with seats left
SELECT e.title, e.venue, e.start_at,
       e.capacity - COUNT(r.id) AS seats_left
FROM events_event e
LEFT JOIN events_registration r ON r.event_id = e.id
WHERE e.start_at >= NOW()
GROUP BY e.id
ORDER BY e.start_at;

-- Update
UPDATE events_event SET capacity = 50 WHERE id = 1;

-- Delete
DELETE FROM events_registration WHERE event_id = 1 AND user_id = 2;
