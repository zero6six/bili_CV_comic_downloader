import argparse
import asyncio
import json
import os
import random
import re
import shutil
import time
from pathlib import Path

import requests
from bilibili_api import article, opus
from cbz.comic import ComicInfo
from cbz.constants import PageType, YesNo, Manga, AgeRating, Format
from cbz.page import PageInfo
from rich import print

ID = []
COUNT = 1

def clean_filename(filename):
    invalid_chars = r'[\\/:*?"<>|]'
    return re.sub(invalid_chars, "_", filename)


def get_downloaded_list(lid):
    global ID, COUNT
    if not os.path.exists(f"{lid}.json"):
        return
    with open(f"{lid}.json", "r") as f:
        ID = json.load(f)
    COUNT = len(ID) + 1


def save_downloaded_list(lid):
    with open(f"{lid}.json", "w") as f:
        json.dump(ID, f)


async def get_list(lid):
    id = []
    a = article.ArticleList(rlid=lid)
    info = await a.get_content()
    for item in info['articles']:
        id.append(item['id'])
    return id, info['list']['name']


async def get_co(id):
    """通过 cv 号获取专栏图片，内部转为 Opus 处理"""
    a = article.Article(cvid=id)
    print(f"专栏cv号：{id}")
    o = await a.turn_to_opus()
    return await get_opus_images(o)


async def get_opus(oid):
    """通过 opus id 获取图文图片"""
    o = opus.Opus(opus_id=oid)
    print(f"图文opus号：{oid}")
    return await get_opus_images(o)


async def get_opus_images(o):
    """从 Opus 对象提取图片列表和标题"""
    info = await o.get_info()

    # 从 modules 中获取标题
    cname = "Unknown_Title"
    for module in info.get("item", {}).get("modules", []):
        if module.get("module_title"):
            cname = module["module_title"]["text"]
            break

    # 获取图片 URL 列表
    raw_images = await o.get_images_raw_info()
    images = []
    for pic in raw_images:
        url = pic["url"].replace("http://", "https://")
        if url not in images:
            images.append(url)

    print("图片列表：")
    print(images)
    return images, cname


async def download(path, url):
    filename = path
    print(f"正在下载图片：{url}")
    if os.path.exists(filename):
        print(f"检测到已下载{filename}，跳过")
        return
    response = requests.get(url)
    if not response:
        print(f"图片下载失败，URL：{url}")
        print("建议稍后重试，防止因b站ban IP图片下载不完整")
        return
    with open(filename, "wb") as f:
        f.write(response.content)
    # 防止速率过高导致临时403
    sleep_time = random.randint(1, 2)
    time.sleep(sleep_time)


def c_cbz(path, title_name, cname, cbz_path, cid):
    cbz_path.parent.mkdir(parents=True, exist_ok=True)
    paths = sorted(Path(path).iterdir(), key=lambda x: x.name)
    pages = [
        PageInfo.load(
            path=path,
            type=PageType.FRONT_COVER if i == 0 else PageType.STORY
        )
        for i, path in enumerate(paths)
    ]

    metadata = {
        "pages": pages,
        "title": cname,
        "alternate_number": cid,
        "language_iso": 'zh',
        "format": Format.WEB_COMIC,
        "black_white": YesNo.NO,
        "manga": Manga.YES,
        "age_rating": AgeRating.PENDING,
        "web": f"https://www.bilibili.com/read/cv{cid}"
    }

    if title_name != "Single":
        # 单个专栏/单行本时不传递系列名和编号，防止阅读器解析异常
        metadata["series"] = title_name
        metadata["number"] = COUNT

    comic = ComicInfo.from_pages(**metadata)
    try:
        cbz_path.write_bytes(comic.pack())
    except Exception as e:
        print(e)
        exit(1)
    shutil.rmtree(path)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'id',
        nargs='?',
        help='专栏id(cv)/合集id(rl)/图文id(opus/纯数字)')
    parser.add_argument(
        '--lid',
        help='专栏合集的id (可选，旧参数兼容)')
    parser.add_argument(
        '--cid',
        help='专栏的cvid (可选，旧参数兼容)')
    parser.add_argument(
        '--oid',
        help='图文的opus id (可选，旧参数兼容)')
    parser.add_argument(
        '--cbz',
        help='cbz文件夹位置',
        required=True)

    args = parser.parse_args()
    
    # 参数归一化处理
    input_id = args.id
    lid = args.lid
    cid = args.cid
    oid = args.oid
    cbz_path = args.cbz

    if input_id:
        if "cv" in input_id.lower():
            cid = re.search(r"\d+", input_id).group()
        elif "rl" in input_id.lower():
            lid = re.search(r"\d+", input_id).group()
        else:
            # 纯数字默认为 oid
            oid = re.search(r"\d+", input_id).group()

    # 优先处理单个图文（opus）
    if oid is not None:
        print(f"下载单个图文: {oid}")
        images, cname = await get_opus(int(oid))
        cname = clean_filename(cname)
        path = f"{os.path.abspath('.')}/download/Single/{cname}"
        if not os.path.exists(path):
            os.makedirs(path)

        index = 0
        for image in images:
            ipath = f"{path}/{index:03}.jpg"
            await download(ipath, image)
            index += 1

        if not os.path.exists(f"temp/{cbz_path}/Single/"):
            os.makedirs(f"temp/{cbz_path}/Single/")
        cbz_fpath = Path(f'temp/{cbz_path}/Single/') / f'{cname}.zip'
        c_cbz(path, "Single", cname, cbz_fpath, oid)
        return

    # 处理单个专栏
    if cid is not None:
        print(f"下载单个专栏: {cid}")
        images, cname = await get_co(int(cid))
        cname = clean_filename(cname)
        path = f"{os.path.abspath('.')}/download/Single/{cname}"
        if not os.path.exists(path):
            os.makedirs(path)

        index = 0
        for image in images:
            ipath = f"{path}/{index:03}.jpg"
            await download(ipath, image)
            index += 1

        if not os.path.exists(f"temp/{cbz_path}/Single/"):
            os.makedirs(f"temp/{cbz_path}/Single/")
        cbz_fpath = Path(f'temp/{cbz_path}/Single/') / f'{cname}.zip'
        c_cbz(path, "Single", cname, cbz_fpath, cid)
        return

    # 处理合集
    if lid is not None:
        get_downloaded_list(lid)
        id, title_name = await get_list(int(lid))
        title_name = title_name.replace(" ", "_").replace(":", "：").replace("?", "？")
        if ID:
            cindex = len(ID) + 1
        else:
            cindex = 1
        for x in id:
            if x in ID:
                print(f"{x} 已下载，跳过")
                continue
            index = 0
            images, cname = await get_co(x)
            print(f"正在下载：{cname}")
            cname = clean_filename(cname)
            path = f"{os.path.abspath('.')}/download/{title_name}/{cindex}-{cname}"
            if not os.path.exists(path):
                os.makedirs(path)
            for image in images:
                ipath = f"{path}/{index:03}.jpg"
                await download(ipath, image)
                index += 1
            if not os.path.exists(f"temp/{cbz_path}/{title_name}/"):
                os.makedirs(f"temp/{cbz_path}/{title_name}/")
            cbz_fpath = Path(f'temp/{cbz_path}/{title_name}/') / f'{cindex}-{cname}.zip'
            c_cbz(path, title_name, cname, cbz_fpath, x)
            global COUNT
            COUNT += 1
            cindex += 1
            ID.append(x)
            save_downloaded_list(lid)
        return

    print("没有提供lid、cid或oid，请输入对应id再进行下载")
    exit(1)


if __name__ == "__main__":
    asyncio.run(main())