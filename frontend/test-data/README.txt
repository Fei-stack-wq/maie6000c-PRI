Bundled review test samples

chinese_product_reviews_50.csv: 50 unchanged review texts sampled from SophonPlus/ChineseNlpCorpus, online_shopping_10_cats. Clothing 20, shampoo 15, phones 15. The store/product identifiers are artificial test buckets, not real platform product relationships. Original sentiment labels do not establish issue/no-issue ground truth. Dates and ratings are omitted because the source does not provide them.
https://github.com/SophonPlus/ChineseNlpCorpus/tree/master/datasets/online_shopping_10_cats

amazon_fashion_60.csv: the existing English Amazon Fashion 2018 test sample, with 60 reviews. The sample-shop-not-real store identifier is artificial. Product IDs, review dates and ratings are retained from the prepared sample. Original source:
https://cseweb.ucsd.edu/~jmcauley/datasets/amazon_v2/

Both files are UTF-8 CSVs matching the project upload columns. Downloading does not upload reviews or call a model. Enter a platform identifier (for example cn_public_sample or amazon) and upload the chosen file to run a test batch.

随项目提供的评论测试集

chinese_product_reviews_50.csv：从 ChineseNlpCorpus 的 online_shopping_10_cats 抽取的50条原文，衣服20条、洗发水15条、手机15条。店铺和商品编号为测试分桶，不表示真实商品关系。原情感标签不是问题判断标准；源数据没有日期和评分，因此未补造。
来源链接见上方。

amazon_fashion_60.csv：此前提供的英文 Amazon Fashion 2018 测试样本，共60条。sample-shop-not-real 是测试店铺编号；商品编号、日期及评分保持已有样本内容。原始数据来源链接见上方。

两个文件均为符合项目上传字段的 UTF-8 CSV。点击下载不会自动导入或调用模型。测试时填写平台标识（如 cn_public_sample 或 amazon），再上传所选文件。
