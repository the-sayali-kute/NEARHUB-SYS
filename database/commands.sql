show databases;
use nearhub_platform;
show tables;
select * from users;
select * from hostels;
SHOW COLUMNS FROM menu_items LIKE 'is_available';
ALTER TABLE menu_items
ADD COLUMN is_available BOOLEAN NOT NULL DEFAULT TRUE;
select * from menu_items;
USE nearhub_platform;



ALTER TABLE hostels
ADD COLUMN total_rooms INT NOT NULL DEFAULT 1,
ADD COLUMN available_rooms INT NOT NULL DEFAULT 1;