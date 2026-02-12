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
from bilibili_api import article
from cbz.comic import ComicInfo
from cbz.constants import PageType, YesNo, Manga, AgeRating, Format
from cbz.page import PageInfo
from rich import print

ID = []
COUNT = 1

def clean_filename(filename):
    invalid_chars = r'[\\/:*?"<>|]'
    return re.sub(invalid_chars, "_", filename)

def extract_images_from_json(data):
    images = []

    try:
        # get_detail() 返回的新版 API 结构: root -> opus -> content
        opus_content = data.get("opus", {}).get("content", {})
        
        paragraphs = opus_content.get("paragraphs", [])
        for para in paragraphs:
            # para_type 为 2 通常代表图片节点
            if para.get("para_type") == 2 and "pic" in para:
                for pic in para["pic"].get("pics", []):
                    if "url" in pic:
                        images.append(pic["url"])
    except Exception as e:
        print(f"[bold yellow]警告：尝试从 Opus 结构提取图片失败: {e}[/bold yellow]")

    if not images:
        def traverse_children(children):
            for child in children:
                if child.get("type") == "ImageNode" and "url" in child:
                    images.append(child["url"])
                elif child.get("type") == "TextNode":
                    text = child.get("text", "")
                    image_urls = re.findall(r'https?://i0\.hdslb\.com[^\s"\'}]+', text)
                    images.extend(image_urls)
                elif "children" in child:
                    traverse_children(child["children"])

        traverse_children(data.get("children", []))

    unique_images = []
    for img in images:
        img_url = img.replace("http://", "https://")
        if img_url not in unique_images:
            unique_images.append(img_url)

    return unique_images


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
    a = article.Article(cvid=id)
    print(f"专栏cv号：{id}")
    try:
        # 使用 get_detail() 替代 fetch_content()，因为旧版 API 已失效
        # 参考：https://github.com/Nemo2011/bilibili-api/issues/994
        a_data = await a.get_detail()
    except Exception as e:
        print(f"[red]获取文章内容失败: {e}[/red]")
        a_data = {}

    images = extract_images_from_json(a_data)

    # 优先从根目录获取标题 (get_detail 返回格式)
    cname = a_data.get("title", "Unknown_Title")

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
        '--lid',
        help='专栏合集的id,例如https://www.bilibili.com/read/readlist/rl843588中843588')
    parser.add_argument(
        '--cid',
        help='专栏的cvid,例如https://www.bilibili.com/read/cv40061677中40061677')
    parser.add_argument(
        '--cbz',
        help='cbz文件夹位置')

    args = parser.parse_args()
    lid = args.lid
    cid = args.cid
    cbz_path = args.cbz

    # 优先处理单个专栏
    if cid is not None:
        print(f"下载单个专栏: {cid}")
        images, cname = await get_co(cid)
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
        id, title_name = await get_list(lid)
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

    print("没有提供lid或cid，请输入lid或cid再进行下载")
    exit(1)


if __name__ == "__main__":
    asyncio.run(main())