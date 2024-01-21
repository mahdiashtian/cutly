import datetime
import os
from typing import Optional, List, Type

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import DB_NAME, DB_USER, DB_HOST, DB_PASSWORD
from models import User, File, Channel


def userid_list(db):
    return [user.userid for user in db.query(User).with_entities(User.userid)]


def read_users(db: Session, is_admin=False) -> List[Type[User]]:
    query = db.query(User)

    if is_admin:
        db_users = query.filter(or_(User.is_superuser == True, User.is_staff == True)).all()
    else:
        db_users = query.all()
    db_users.sort(key=lambda x: x.id)

    return db_users


def read_user_from_db(db: Session, user_id: int) -> Optional[Type[User]]:
    return db.query(User).filter(User.userid == user_id).first()


def create_user_from_db(db: Session, data: dict) -> User:
    db_user = User(**data)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


def create_file_from_db(db: Session, data: dict) -> File:
    db_file = File(**data)
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    return db_file


def delete_file_from_db(db: Session, userid: object, code: int) -> None:
    db.query(File).filter(File.code == code, File.owner_id == userid).delete()
    db.commit()


def read_files_from_db(db: Session, code: int = None, userid: int = None) -> List[Type[File]]:
    obj = db.query(File)
    if code is not None:
        obj = obj.filter(File.code == code)
    if userid is not None:
        obj = obj.filter(File.owner_id == userid)
    return obj.all()


def read_file_from_db(db: Session, code: int = None, userid: int = None) -> Optional[Type[File]]:
    obj = read_files_from_db(db, code, userid)
    return obj[0] if obj else None


def change_admin_from_db(db: Session, userid: int, is_superuser: bool = None, is_staff: bool = None) -> bool:
    db_user = read_user_from_db(db, userid)
    if db_user:
        if is_superuser is not None:
            db_user.is_superuser = is_superuser
        if is_staff is not None:
            db_user.is_staff = is_staff
        db.commit()
        return True
    return False


def read_channels_from_db(db: Session) -> List[Type[File]]:
    return db.query(Channel).all()


def delete_channel_from_db(db: Session, channel_id: str) -> bool:
    result = db.query(Channel).filter(
        or_(Channel.channel_id == channel_id, Channel.channel_link == channel_id))
    if result.first():
        result.delete()
        db.commit()
        return True
    return False


def create_channel_from_db(db: Session, data: dict) -> Channel:
    db_channel = Channel(**data)
    db.add(db_channel)
    db.commit()
    db.refresh(db_channel)

    return db_channel


def create_backup():
    time = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    file_name = f"backup-{time}.sql"
    os.environ["PGPASSWORD"] = DB_PASSWORD
    result = os.system(f"pg_dump -U {DB_USER} -h {DB_HOST} {DB_NAME} > {file_name}")
    os.environ.pop("PGPASSWORD", None)
    dir_path = os.path.dirname(os.path.realpath(__file__))
    if result == 0:
        return f"{dir_path}/{file_name}"
    return None


async def channel_list(db, app):
    data = {}
    channels = read_channels_from_db(db)
    if channels:
        for channel in channels:
            chnnael_data = await app.get_chat(channel.channel_id)
            data[channel.channel_id] = {"title": chnnael_data.title, "link": channel.channel_link}
        return data
    return 1
